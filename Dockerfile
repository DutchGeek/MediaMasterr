# syntax=docker/dockerfile:1.7
# cSpell:disable

## frontend build stage
FROM node:25-alpine3.22 AS frontend-build
WORKDIR /workspace/frontend
ARG VITE_APP_CHANNEL=dev
COPY frontend/package.json ./package.json
RUN npm install
COPY frontend ./
COPY branding ../branding
RUN VITE_APP_CHANNEL=${VITE_APP_CHANNEL} npm run build

## backend base image
FROM python:3.13-slim AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	FRONTEND_DIST=/app/frontend/dist
WORKDIR /app
RUN apt-get update \
	&& DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential curl gosu tzdata \
	&& rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md CHANGELOG.md ./
COPY backend ./backend
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN python -m pip install --upgrade pip \
	&& python -m pip install .
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
	&& mkdir -p /app/data/database /app/data/logs /app/data/static/avatars
EXPOSE 8000

## API image (includes frontend build)
FROM backend-base AS api
ARG BUILD_VERSION=0.0.0
ARG BUILD_COMMIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ARG BUILD_REPOSITORY=https://github.com/dutchgeek/mediamasterr
ARG BUILD_DOCKER_IMAGE=ghcr.io/dutchgeek/mediamasterr
ARG BUILD_CONTAINER_DIGEST=unknown
LABEL org.opencontainers.image.title="MediaMasterr" \
	  org.opencontainers.image.description="Media server cleanup and deletion management tool" \
	  org.opencontainers.image.source="${BUILD_REPOSITORY}" \
	  org.opencontainers.image.url="${BUILD_REPOSITORY}" \
	  org.opencontainers.image.version="${BUILD_VERSION}" \
	  org.opencontainers.image.revision="${BUILD_COMMIT_SHA}" \
	  org.opencontainers.image.created="${BUILD_TIMESTAMP}"
ENV APP_COMMIT_SHA=${BUILD_COMMIT_SHA} \
	APP_BUILD_TIMESTAMP=${BUILD_TIMESTAMP} \
	APP_DOCKER_IMAGE=${BUILD_DOCKER_IMAGE} \
	APP_CONTAINER_DIGEST=${BUILD_CONTAINER_DIGEST} \
	APP_GIT_REPOSITORY=${BUILD_REPOSITORY}
COPY --from=frontend-build /workspace/frontend/dist /app/frontend/dist
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["sh", "-c", \
	"exec granian --interface asgi --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000} backend.api.main:app"]
