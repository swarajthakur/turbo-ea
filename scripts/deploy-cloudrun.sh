#!/usr/bin/env bash
# Deploy Turbo EA to Cloud Run as a single multi-container service.
#
# `gcloud run compose up` only takes --region/--project/--allow-unauthenticated/
# --build; everything else (per-container CPU + memory, secrets, service account,
# min-instances, CPU allocation) has to be applied afterwards with
# `gcloud run services update`. That is why this is a script and not one command.
#
# Re-running is safe and is also how you roll out changes.
#
# Prereqs, once per project:
#   gcloud services enable run.googleapis.com sqladmin.googleapis.com \
#       cloudbuild.googleapis.com artifactregistry.googleapis.com \
#       secretmanager.googleapis.com
#   scripts/deploy-cloudrun.sh bootstrap     # creates SQL instance, SA, secrets
#
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-turbo-ea}"

# Public access is opt-in. Turbo EA has its own login, but leaving the service
# IAM-gated keeps the login page off the open internet; reach it with
#   gcloud run services proxy "$SERVICE" --region "$REGION"
# after granting yourself roles/run.invoker.
ALLOW_UNAUTH="${ALLOW_UNAUTH:-false}"
case "$ALLOW_UNAUTH" in
  true|1|yes) AUTH_FLAG=--allow-unauthenticated ;;
  *)          AUTH_FLAG=--no-allow-unauthenticated ;;
esac

# Where Postgres lives.
#   cloudsql  — Cloud SQL reached through the proxy sidecar (default).
#   neon      — any external Postgres (Neon, Supabase, ...). The sidecar is
#               dropped from the rendered compose file and the backend talks
#               straight to NEON_HOST over TLS. Nothing Cloud SQL is created.
DB_MODE="${DB_MODE:-cloudsql}"

SQL_TIER="${SQL_TIER:-db-f1-micro}"
SQL_INSTANCE="${SQL_INSTANCE:-turbo-ea-db}"
POSTGRES_DB="${POSTGRES_DB:-turboea}"
POSTGRES_USER="${POSTGRES_USER:-turboea}"

case "$DB_MODE" in
  cloudsql)
    POSTGRES_HOST=127.0.0.1
    POSTGRES_PORT=5432
    POSTGRES_SSL=""            # the proxy already terminates TLS
    DB_DISABLE_PREPARED_CACHE="false"
    ;;
  neon)
    # Use the DIRECT endpoint, not the "-pooler" one: no pgbouncer means no
    # prepared-statement workaround, and a small pool stays well inside the
    # free tier's connection budget. If you do point at a pooled endpoint,
    # set DB_DISABLE_PREPARED_CACHE=true.
    POSTGRES_HOST="${NEON_HOST:?set NEON_HOST (e.g. ep-xxx.eu-west-2.aws.neon.tech)}"
    POSTGRES_PORT="${NEON_PORT:-5432}"
    POSTGRES_SSL="${POSTGRES_SSL:-require}"
    DB_DISABLE_PREPARED_CACHE="${DB_DISABLE_PREPARED_CACHE:-false}"
    ;;
  *) echo "DB_MODE must be 'cloudsql' or 'neon', got '$DB_MODE'" >&2; exit 2 ;;
esac

DB_POOL_SIZE="${DB_POOL_SIZE:-5}"
DB_MAX_OVERFLOW="${DB_MAX_OVERFLOW:-2}"
# Secret Manager secret names. The DB password one is configurable because it
# is often created out of band, under whatever name the operator chose.
DB_PASSWORD_SECRET="${DB_PASSWORD_SECRET:-turbo-ea-db-password}"
SECRET_KEY_SECRET="${SECRET_KEY_SECRET:-turbo-ea-secret-key}"

SA_NAME="${SA_NAME:-turbo-ea-run}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
CLOUDSQL_INSTANCE="${PROJECT}:${REGION}:${SQL_INSTANCE}"

# Per-container limits. Cloud Run bills the SUM of these as the instance size,
# so keep the total on a valid instance shape — this adds up to 1 vCPU / 2Gi.
# Only the backend does real work; nginx and the static frontend are close to
# idle, and the proxy is a single Go binary.
#
# UNVERIFIED: the exact per-container CPU split has not been applied against a
# live service yet. If Cloud Run rejects the fractional values, give every
# container 1 and let the instance be 5 vCPU, or drop mcp-server if unused.
declare -A CPU=(  [nginx]=0.2  [frontend]=0.15 [backend]=0.4 [mcp-server]=0.15 [cloudsql-proxy]=0.1 )
declare -A MEM=(  [nginx]=256Mi [frontend]=256Mi [backend]=1Gi [mcp-server]=256Mi [cloudsql-proxy]=256Mi )

# Scale to zero by default: you pay per request rather than continuously. The
# cost is a slow first request after idle — four container starts plus an
# alembic migration run. Set MIN_INSTANCES=1 to trade money for latency.
MIN_INSTANCES="${MIN_INSTANCES:-0}"
CPU_ALLOCATION="${CPU_ALLOCATION:---cpu-throttling}"

IMAGE_REPO="${IMAGE_REPO:-${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/turbo-ea}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------------------
build() {
  log "Building the four stages with explicit --target (cloudbuild.yaml)"
  gcloud builds submit --project="$PROJECT" --region="$REGION" \
    --config=cloudbuild.yaml \
    --substitutions="_REPO=${IMAGE_REPO},_TAG=${IMAGE_TAG}" .
}

# Resolve each tag to a digest. Deploying by digest rather than by tag means the
# revision cannot silently pick up a different image later, and it makes a
# mismatch (wrong stage, stale build) visible here rather than at startup.
resolve_images() {
  local svc digest
  for svc in backend frontend mcp-server nginx; do
    digest=$(gcloud artifacts docker images describe \
      "${IMAGE_REPO}/${svc}:${IMAGE_TAG}" --project="$PROJECT" \
      --format='value(image_summary.digest)' 2>/dev/null || true)
    if [ -z "$digest" ]; then
      echo "No image for ${IMAGE_REPO}/${svc}:${IMAGE_TAG} — run '$0 build' first" >&2
      exit 1
    fi
    case "$svc" in
      backend)    IMAGE_BACKEND="${IMAGE_REPO}/backend@${digest}" ;;
      frontend)   IMAGE_FRONTEND="${IMAGE_REPO}/frontend@${digest}" ;;
      mcp-server) IMAGE_MCP="${IMAGE_REPO}/mcp-server@${digest}" ;;
      nginx)      IMAGE_NGINX="${IMAGE_REPO}/nginx@${digest}" ;;
    esac
  done
}

# ---------------------------------------------------------------------------
bootstrap() {
  local pw="" key secret_exists=false
  key="$(openssl rand -hex 32)"

  # Checked up front so the DB password can be loaded into Secret Manager out
  # of band — the operator never has to hand it to this script at all.
  gcloud secrets describe "$DB_PASSWORD_SECRET" --project="$PROJECT" >/dev/null 2>&1 \
    && secret_exists=true

  if [ "$DB_MODE" = cloudsql ]; then
    log "Creating Cloud SQL instance ${SQL_INSTANCE} (this takes several minutes)"
    gcloud sql instances create "$SQL_INSTANCE" \
      --project="$PROJECT" --region="$REGION" \
      --database-version=POSTGRES_16 --tier="${SQL_TIER:-db-f1-micro}" \
      --storage-auto-increase 2>/dev/null || echo "  (already exists)"

    gcloud sql databases create "$POSTGRES_DB" --instance="$SQL_INSTANCE" \
      --project="$PROJECT" 2>/dev/null || echo "  (database already exists)"

    pw="$(openssl rand -base64 32 | tr -d '\n/+=' | cut -c1-32)"
  else
    # Nothing to create — the database already exists at the provider. All we
    # need is its password in Secret Manager. If it is already there (loaded
    # directly, so it never passes through this script or a shell history),
    # NEON_PASSWORD is not required.
    log "DB_MODE=neon — no Cloud SQL resources will be created"
    [ "$secret_exists" = true ] \
      || pw="${NEON_PASSWORD:?turbo-ea-db-password does not exist yet: either create it directly, or set NEON_PASSWORD}"
  fi

  log "Creating secrets"
  if [ "$secret_exists" = false ]; then
    printf '%s' "$pw" | gcloud secrets create "$DB_PASSWORD_SECRET" \
      --project="$PROJECT" --data-file=- --replication-policy=automatic
    [ "$DB_MODE" = cloudsql ] && gcloud sql users create "$POSTGRES_USER" \
      --instance="$SQL_INSTANCE" --project="$PROJECT" --password="$pw"
  else
    echo "  (db password secret already exists — leaving it alone)"
    echo "  to rotate: printf '%s' NEW | gcloud secrets versions add $DB_PASSWORD_SECRET --data-file=-"
  fi

  if ! gcloud secrets describe "$SECRET_KEY_SECRET" --project="$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$key" | gcloud secrets create "$SECRET_KEY_SECRET" \
      --project="$PROJECT" --data-file=- --replication-policy=automatic
  fi

  log "Creating service account ${SA_EMAIL}"
  gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT" \
    --display-name="Turbo EA Cloud Run" 2>/dev/null || echo "  (already exists)"

  local roles=(roles/secretmanager.secretAccessor)
  [ "$DB_MODE" = cloudsql ] && roles+=(roles/cloudsql.client)
  for role in "${roles[@]}"; do
    gcloud projects add-iam-policy-binding "$PROJECT" \
      --member="serviceAccount:${SA_EMAIL}" --role="$role" --condition=None \
      --quiet >/dev/null
  done
  log "Bootstrap done. Now run: $0"
}

# ---------------------------------------------------------------------------
render() {
  # Substitute placeholders ourselves rather than relying on gcloud doing
  # compose-style ${VAR} interpolation — if it did not, the literal "${...}"
  # would land in the container env and fail silently at runtime.
  resolve_images
  export TURBO_EA_PUBLIC_URL POSTGRES_DB POSTGRES_USER CLOUDSQL_INSTANCE \
         POSTGRES_HOST POSTGRES_PORT POSTGRES_SSL \
         DB_POOL_SIZE DB_MAX_OVERFLOW DB_DISABLE_PREPARED_CACHE \
         IMAGE_BACKEND IMAGE_FRONTEND IMAGE_MCP IMAGE_NGINX
  envsubst '${TURBO_EA_PUBLIC_URL} ${POSTGRES_DB} ${POSTGRES_USER} ${CLOUDSQL_INSTANCE}
            ${POSTGRES_HOST} ${POSTGRES_PORT} ${POSTGRES_SSL}
            ${DB_POOL_SIZE} ${DB_MAX_OVERFLOW} ${DB_DISABLE_PREPARED_CACHE}
            ${IMAGE_BACKEND} ${IMAGE_FRONTEND} ${IMAGE_MCP} ${IMAGE_NGINX}' \
    < compose.cloudrun.yaml > .compose.cloudrun.rendered.yaml

  if [ "$DB_MODE" = neon ]; then
    # Drop the proxy sidecar and any dependency on it. Done with a YAML parser
    # rather than sed so an indentation change in the source file cannot
    # silently produce a half-removed service.
    python3 - <<'PY'
import yaml
p = ".compose.cloudrun.rendered.yaml"
d = yaml.safe_load(open(p))
d["services"].pop("cloudsql-proxy", None)
for svc in d["services"].values():
    dep = svc.get("depends_on")
    if isinstance(dep, list) and "cloudsql-proxy" in dep:
        dep.remove("cloudsql-proxy")
        if not dep:
            svc.pop("depends_on")
yaml.safe_dump(d, open(p, "w"), sort_keys=False, default_flow_style=False)
PY
  fi
}

# The revision `compose up` creates is EXPECTED to fail. Compose has no way to
# reference Secret Manager, so the backend starts without SECRET_KEY and
# POSTGRES_PASSWORD and exits during app startup. apply_settings() below creates
# the revision that actually runs — that is the one that has to succeed.
compose_up() {
  render
  log "gcloud run compose up (${SERVICE} in ${REGION})"
  gcloud run compose up .compose.cloudrun.rendered.yaml \
    --project="$PROJECT" --region="$REGION" "$AUTH_FLAG" --no-build \
    || log "compose up produced no running revision (expected: secrets are not attached yet)"
}

# Everything compose cannot express, in ONE update so it is ONE revision.
# Flags after --container apply to that container, so per-container resources
# and the backend's secrets go in the same call. Splitting these up would cost
# a failed revision — and several minutes of startup-probe timeout — each.
apply_settings() {
  log "Applying secrets, service account and resource limits"
  [ "$DB_MODE" = neon ] && { unset 'CPU[cloudsql-proxy]' 'MEM[cloudsql-proxy]'; }

  local args=(--service-account="$SA_EMAIL"
              --min-instances="$MIN_INSTANCES" --max-instances=2
              "$CPU_ALLOCATION" --timeout=3600)
  local c
  for c in "${!CPU[@]}"; do
    args+=(--container="$c" --cpu="${CPU[$c]}" --memory="${MEM[$c]}")
    if [ "$c" = backend ]; then
      args+=(--set-secrets="POSTGRES_PASSWORD=${DB_PASSWORD_SECRET}:latest,SECRET_KEY=${SECRET_KEY_SECRET}:latest")
    fi
  done

  gcloud run services update "$SERVICE" --project="$PROJECT" --region="$REGION" \
    "${args[@]}" --quiet
}

service_url() {
  gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
    --format='value(status.url)' 2>/dev/null || true
}

deploy() {
  [ "${SKIP_BUILD:-false}" = true ] || build

  # Pass 1 exists only to learn the assigned *.run.app URL, which nginx (server
  # name, X-Forwarded-Proto), the backend (CORS) and the MCP server (OAuth
  # discovery documents) all need baked into their env.
  TURBO_EA_PUBLIC_URL="$(service_url)"
  local first_deploy=false
  if [ -z "$TURBO_EA_PUBLIC_URL" ]; then
    first_deploy=true
    TURBO_EA_PUBLIC_URL="https://placeholder.invalid"
    log "First deploy — the public URL is not known yet, deploying twice"
  fi

  compose_up
  apply_settings

  if [ "$first_deploy" = true ]; then
    TURBO_EA_PUBLIC_URL="$(service_url)"
    log "Assigned URL is ${TURBO_EA_PUBLIC_URL} — redeploying with it baked in"
    compose_up
    apply_settings          # compose up rewrites the whole service spec
  fi

  local ready
  ready=$(gcloud run services describe "$SERVICE" --project="$PROJECT" \
    --region="$REGION" --format='value(status.latestReadyRevisionName)')
  log "Done: $(service_url)  (serving revision: ${ready:-NONE})"
}

case "${1:-deploy}" in
  bootstrap) bootstrap ;;
  build)     build ;;
  deploy)    deploy ;;
  render)    TURBO_EA_PUBLIC_URL="$(service_url)"; render; cat .compose.cloudrun.rendered.yaml ;;
  *) echo "usage: $0 [bootstrap|build|deploy|render]" >&2; exit 2 ;;
esac
