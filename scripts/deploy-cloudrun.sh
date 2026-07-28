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

SQL_TIER="${SQL_TIER:-db-f1-micro}"
SQL_INSTANCE="${SQL_INSTANCE:-turbo-ea-db}"
POSTGRES_DB="${POSTGRES_DB:-turboea}"
POSTGRES_USER="${POSTGRES_USER:-turboea}"
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

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------------------
bootstrap() {
  log "Creating Cloud SQL instance ${SQL_INSTANCE} (this takes several minutes)"
  gcloud sql instances create "$SQL_INSTANCE" \
    --project="$PROJECT" --region="$REGION" \
    --database-version=POSTGRES_16 --tier="${SQL_TIER:-db-f1-micro}" \
    --storage-auto-increase 2>/dev/null || echo "  (already exists)"

  gcloud sql databases create "$POSTGRES_DB" --instance="$SQL_INSTANCE" \
    --project="$PROJECT" 2>/dev/null || echo "  (database already exists)"

  log "Creating secrets"
  local pw key
  pw="$(openssl rand -base64 32 | tr -d '\n/+=' | cut -c1-32)"
  key="$(openssl rand -hex 32)"

  if ! gcloud secrets describe turbo-ea-db-password --project="$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$pw" | gcloud secrets create turbo-ea-db-password \
      --project="$PROJECT" --data-file=- --replication-policy=automatic
    gcloud sql users create "$POSTGRES_USER" --instance="$SQL_INSTANCE" \
      --project="$PROJECT" --password="$pw"
  else
    echo "  (db password secret already exists — leaving the SQL user alone)"
  fi

  if ! gcloud secrets describe turbo-ea-secret-key --project="$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$key" | gcloud secrets create turbo-ea-secret-key \
      --project="$PROJECT" --data-file=- --replication-policy=automatic
  fi

  log "Creating service account ${SA_EMAIL}"
  gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT" \
    --display-name="Turbo EA Cloud Run" 2>/dev/null || echo "  (already exists)"

  for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
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
  export TURBO_EA_PUBLIC_URL POSTGRES_DB POSTGRES_USER CLOUDSQL_INSTANCE
  envsubst '${TURBO_EA_PUBLIC_URL} ${POSTGRES_DB} ${POSTGRES_USER} ${CLOUDSQL_INSTANCE}' \
    < compose.cloudrun.yaml > .compose.cloudrun.rendered.yaml
}

service_url() {
  gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
    --format='value(status.url)' 2>/dev/null || true
}

deploy() {
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

  render
  log "gcloud run compose up (${SERVICE} in ${REGION})"
  gcloud run compose up .compose.cloudrun.rendered.yaml \
    --project="$PROJECT" --region="$REGION" "$AUTH_FLAG"

  log "Applying Cloud Run settings compose cannot express"
  gcloud run services update "$SERVICE" --project="$PROJECT" --region="$REGION" \
    --service-account="$SA_EMAIL" \
    --min-instances="$MIN_INSTANCES" --max-instances=2 \
    "$CPU_ALLOCATION" \
    --timeout=3600 \
    --quiet

  for c in "${!CPU[@]}"; do
    gcloud run services update "$SERVICE" --project="$PROJECT" --region="$REGION" \
      --container="$c" --cpu="${CPU[$c]}" --memory="${MEM[$c]}" --quiet
  done

  gcloud run services update "$SERVICE" --project="$PROJECT" --region="$REGION" \
    --container=backend \
    --set-secrets=POSTGRES_PASSWORD=turbo-ea-db-password:latest,SECRET_KEY=turbo-ea-secret-key:latest \
    --quiet

  if [ "$first_deploy" = true ]; then
    TURBO_EA_PUBLIC_URL="$(service_url)"
    log "Assigned URL is ${TURBO_EA_PUBLIC_URL} — redeploying with it baked in"
    render
    gcloud run compose up .compose.cloudrun.rendered.yaml \
      --project="$PROJECT" --region="$REGION" "$AUTH_FLAG"
  fi

  log "Done: $(service_url)"
}

case "${1:-deploy}" in
  bootstrap) bootstrap ;;
  deploy)    deploy ;;
  render)    TURBO_EA_PUBLIC_URL="$(service_url)"; render; cat .compose.cloudrun.rendered.yaml ;;
  *) echo "usage: $0 [bootstrap|deploy|render]" >&2; exit 2 ;;
esac
