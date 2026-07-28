ARG APP_UID=1000
ARG APP_GID=1000

FROM python:3.12-alpine AS backend-build

RUN apk add --no-cache gcc musl-dev

WORKDIR /app

COPY backend/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && \
    pip install --no-cache-dir --prefix=/install . && \
    rm -rf app

COPY VERSION ./VERSION
COPY backend/ ./
RUN pip install --no-cache-dir --no-deps --prefix=/install .


FROM python:3.12-alpine AS backend

ARG APP_UID
ARG APP_GID

RUN apk upgrade --no-cache && rm -rf /var/cache/apk/*
RUN addgroup -g ${APP_GID} -S appgroup && adduser -S -D -u ${APP_UID} -G appgroup appuser

WORKDIR /app

COPY --from=backend-build /install /usr/local
COPY --from=backend-build /app/VERSION ./VERSION
COPY --from=backend-build /app/app ./app
COPY --from=backend-build /app/alembic ./alembic
COPY --from=backend-build /app/alembic.ini ./alembic.ini
COPY --from=backend-build /app/bpmn_templates ./bpmn_templates

# Upgrade the bundled pip past CVE-2025-8869 / CVE-2026-1703 / CVE-2026-6357.
# pip is never executed at runtime — this only silences Trivy noise on the image.
RUN pip install --no-cache-dir --upgrade 'pip>=26.1'

# /app/data is the mountpoint of the backend_data named volume (uploads,
# installed extensions, workspace transfers). It MUST exist in the image
# owned by appuser: Docker copies the mountpoint's ownership into a fresh
# named volume, and without this the volume is created root-owned — the
# non-root backend (cap_drop: ALL) then cannot write any upload.
RUN mkdir -p /app/data && chown -R ${APP_UID}:${APP_GID} /app

USER ${APP_UID}:${APP_GID}

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]


FROM postgres:18-alpine AS db

ARG APP_UID
ARG APP_GID

RUN apk upgrade --no-cache && \
    apk add --no-cache shadow && \
    groupmod -g ${APP_GID} postgres && \
    usermod -u ${APP_UID} -g ${APP_GID} postgres && \
    apk del shadow && \
    # The upstream postgres-alpine image bundles a gosu binary built against
    # an older Go stdlib. The entrypoint only invokes it when running as root
    # (id -u == 0) to drop privileges to the postgres user — but we set USER
    # to a fixed non-root UID below, so the gosu branch is never taken.
    # Deleting the binary closes 8 Go-stdlib CVEs that Trivy flags on every
    # image scan without changing runtime behaviour.
    rm -f /usr/local/bin/gosu /usr/local/bin/gosu.asc && \
    mkdir -p /var/lib/postgresql/data /var/run/postgresql && \
    chown -R ${APP_UID}:${APP_GID} /var/lib/postgresql /var/run/postgresql && \
    chmod 700 /var/lib/postgresql/data && \
    chmod 3775 /var/run/postgresql

USER ${APP_UID}:${APP_GID}


FROM node:24-alpine AS frontend-build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json frontend/xlsx-0.20.3.tgz ./
RUN npm ci
COPY VERSION ./VERSION
COPY frontend/ ./
RUN npm run build


FROM alpine/git:v2.47.2 AS drawio

RUN git clone --depth 1 --branch v26.0.9 https://github.com/jgraph/drawio.git /drawio


FROM nginx:1.30.3-alpine AS frontend

ARG APP_UID
ARG APP_GID

RUN apk upgrade --no-cache && rm -rf /var/cache/apk/*
RUN addgroup -g ${APP_GID} -S appgroup && adduser -S -D -H -u ${APP_UID} -G appgroup appuser

COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=drawio /drawio/src/main/webapp /usr/share/nginx/drawio
COPY frontend/drawio-config/PreConfig.js /usr/share/nginx/drawio/js/PreConfig.js
COPY frontend/drawio-config/PostConfig.js /usr/share/nginx/drawio/js/PostConfig.js

# WEB-INF is the Java-servlet deployment path of the upstream drawio webapp
# (commons-fileupload, commons-io, commons-lang3 JARs). nginx serves drawio
# as static files only and there is no JRE in this image — drop the dead
# JARs so Trivy stops re-flagging upstream Java CVEs that we cannot reach.
RUN rm -rf /usr/share/nginx/drawio/WEB-INF

RUN sed -i \
    -e '/<link rel="manifest"/d' \
    -e '/serviceWorker/d' \
    -e 's/<head>/<head><!--email_off-->/' \
    /usr/share/nginx/drawio/index.html

RUN mkdir -p /var/cache/nginx /var/run && \
    touch /var/run/nginx.pid && \
    chown -R ${APP_UID}:${APP_GID} /usr/share/nginx/html /usr/share/nginx/drawio /var/cache/nginx /var/log/nginx /run

USER ${APP_UID}:${APP_GID}

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]


# Same static server, moved off 8080. Cloud Run runs every container of a
# service in a single network namespace, so the edge nginx and this one cannot
# both bind 8080 — see compose.cloudrun.yaml. Nothing else uses this stage;
# docker-compose.yml keeps the plain "frontend" stage on 8080.
FROM frontend AS frontend-cloudrun

ARG APP_UID
ARG APP_GID

USER root
RUN sed -i 's/^\( *\)listen 8080;/\1listen 8081;/' /etc/nginx/conf.d/default.conf && \
    grep -q 'listen 8081;' /etc/nginx/conf.d/default.conf
USER ${APP_UID}:${APP_GID}

EXPOSE 8081
CMD ["nginx", "-g", "daemon off;"]


FROM nginx:1.30.3-alpine AS nginx

ARG APP_UID
ARG APP_GID

RUN apk upgrade --no-cache && rm -rf /var/cache/apk/*
RUN addgroup -g ${APP_GID} -S appgroup && adduser -S -D -H -u ${APP_UID} -G appgroup appuser

COPY nginx/default.conf /etc/nginx/turboea-templates/default.conf.template

COPY nginx/turboea-nginx-entrypoint /usr/local/bin/turboea-nginx-entrypoint

RUN mkdir -p /etc/nginx/templates /etc/nginx/turboea-templates /var/cache/nginx /var/run && \
    touch /var/run/nginx.pid && \
    rm -f /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh && \
    sed -i '/^user\s\+/d' /etc/nginx/nginx.conf && \
    chmod 755 /usr/local/bin/turboea-nginx-entrypoint && \
    chown -R ${APP_UID}:${APP_GID} /etc/nginx/conf.d /etc/nginx/turboea-templates /etc/nginx/templates /var/cache/nginx /var/log/nginx /run

USER ${APP_UID}:${APP_GID}

EXPOSE 8080
CMD ["/usr/local/bin/turboea-nginx-entrypoint"]


FROM ollama/ollama:latest AS ollama

ARG APP_UID
ARG APP_GID

USER root

ENV OLLAMA_MODELS=/models

RUN mkdir -p /models && \
    chown -R ${APP_UID}:${APP_GID} /models

USER ${APP_UID}:${APP_GID}


FROM python:3.12-alpine AS mcp-server

ARG APP_UID
ARG APP_GID

RUN apk upgrade --no-cache && rm -rf /var/cache/apk/*

WORKDIR /app

COPY VERSION ./VERSION
COPY mcp-server/ ./
# Upgrade the bundled pip past CVE-2025-8869 / CVE-2026-1703 / CVE-2026-6357
# before installing the app. pip is never executed at runtime — this only
# silences Trivy noise on the published image.
RUN pip install --no-cache-dir --upgrade 'pip>=26.1' && \
    pip install --no-cache-dir .

RUN addgroup -g ${APP_GID} -S appgroup && adduser -S -D -u ${APP_UID} -G appgroup appuser && \
    chown -R ${APP_UID}:${APP_GID} /app
USER ${APP_UID}:${APP_GID}

EXPOSE 8001
CMD ["python", "-m", "turbo_ea_mcp", "--host", "0.0.0.0", "--port", "8001"]
