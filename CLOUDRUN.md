# Deploying Turbo EA to Cloud Run

Cloud Run's Compose support (`gcloud run compose up`, GA since March 2026) deploys
a compose file as **one Cloud Run service with several sidecar containers**, not as
several services. That constraint drives everything below.

`docker-compose.yml` is unchanged and still the way to run locally. Cloud Run uses
`compose.cloudrun.yaml` + `scripts/deploy-cloudrun.sh`.

## What differs from the local stack

| Local (`docker-compose.yml`) | Cloud Run (`compose.cloudrun.yaml`) |
| --- | --- |
| `db` (postgres:18-alpine + volume) | Cloud SQL for PostgreSQL + `cloudsql-proxy` sidecar |
| `frontend` on 8080 | `frontend` on **8081** (stage `frontend-cloudrun`) |
| nginx resolves `backend`/`frontend` by DNS | nginx points at `127.0.0.1:<port>` |
| `ollama` (profile `ai`) | dropped — needs a GPU and a multi-GB model volume |
| TLS terminated by nginx on 8443 | TLS terminated by Cloud Run |
| Postgres password in `.env` | Secret Manager |

Three of those are not preferences, they are requirements:

1. **Unique ports.** All containers in a Cloud Run service share one network
   namespace. Two containers cannot both bind 8080, so the static frontend moves to
   8081. `frontend-cloudrun` is the `frontend` stage with the listen port rewritten;
   nothing else changes.

2. **IP upstreams.** Cloud Run puts sibling container names in `/etc/hosts`. nginx's
   `resolver` does not read `/etc/hosts`, and this config proxies through *variable*
   upstreams (`set $backend_upstream ...`), which resolve per request. A hostname
   upstream therefore 502s on every request regardless of what `NGINX_RESOLVER` is
   set to. The `TURBO_EA_BACKEND_UPSTREAM` / `_FRONTEND_` / `_MCP_` env vars exist for
   this; pointed at IPs, no resolver is consulted at all.

3. **No `db` container.** Cloud Run instances are ephemeral and its volumes are
   Cloud Storage buckets over FUSE — no POSIX locking, no reliable `fsync`. Postgres
   cannot run on that. It has to be Cloud SQL.

## Deploy

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com

export PROJECT=my-gcp-project
export REGION=us-central1

scripts/deploy-cloudrun.sh bootstrap   # Cloud SQL instance, service account, secrets
scripts/deploy-cloudrun.sh             # build + deploy; re-run to roll out changes
```

The first deploy runs twice on purpose. nginx (`server_name`, `X-Forwarded-Proto`),
the backend (CORS) and the MCP server (OAuth discovery documents) all need the public
URL in their environment, and the `*.run.app` URL is only assigned once the service
exists. Later deploys read the existing URL and go once.

`gcloud run compose up` only accepts `--project`, `--region`,
`--allow-unauthenticated`, `--build`/`--no-build` and `--dry-run`. Per-container CPU
and memory, secrets, the service account, min-instances and CPU allocation are applied
afterwards by the script with `gcloud run services update`. **If you ever run
`gcloud run compose up` by hand, re-run the script afterwards** or those settings are
lost.

Validate without deploying:

```bash
scripts/deploy-cloudrun.sh render      # show the substituted compose file
gcloud run compose up .compose.cloudrun.rendered.yaml --dry-run --region=$REGION
```

## Known rough edges

- **Migrations race the proxy on cold start.** The backend runs `alembic upgrade` at
  startup and needs `cloudsql-proxy` listening. `depends_on` fixes start *order* but
  Cloud Run does not wait for readiness without a startup probe, so a cold instance
  may crash-loop once before coming up. `--min-instances=1` (set by the script) keeps
  this off the request path.
- **Workspace import is capped well below 512m.** The nginx config allows 512m on
  `/api/v1/admin/workspace/import`, but Cloud Run caps request bodies at 32 MiB.
  Large workspace imports have to go another way.
- **Cost.** `--min-instances=1 --no-cpu-throttling` means one always-on 4 vCPU / 4 GiB
  instance plus the Cloud SQL instance. Dropping to `--min-instances=0` is much
  cheaper but makes every cold start pay for five container starts and a migration
  run.
- **AI features are off.** Set `AI_PROVIDER_URL` / `AI_MODEL` on the `backend`
  container to point at a hosted model. Cloud Run does support GPUs if you genuinely
  want Ollama back, but the model cache would sit on a FUSE-mounted bucket.
