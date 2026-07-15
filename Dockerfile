# syntax=docker/dockerfile:1.7
# cSpell:disable

## frontend build stage
FROM node:25-alpine3.22 AS frontend-build
WORKDIR /workspace/frontend
ARG VITE_APP_CHANNEL=dev
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
COPY branding ../branding
RUN VITE_APP_CHANNEL=${VITE_APP_CHANNEL} npm run build \
	&& test -f dist/branding/logo.png \
	&& test -f dist/branding/media-placeholder.png \
	&& ! find dist/branding -type f -name '*.svg' | grep -q .

## backend base image
FROM python:3.13-slim AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	DATA_DIR=/config \
	STATIC_DIR=/config/static \
	AVATARS_DIR=/config/static/avatars \
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
	&& mkdir -p /config/database /config/logs /config/static/avatars
EXPOSE 8000

## API image (includes frontend build)
FROM backend-base AS api
ARG BUILD_VERSION=0.0.0
ARG BUILD_COMMIT_SHA=unknown
ARG BUILD_SHORT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ARG BUILD_DOCKER_TAG=unknown
ARG BUILD_RELEASE_CHANNEL=dev
ARG BUILD_WORKFLOW_RUN_NUMBER=unknown
ARG BUILD_WORKFLOW_RUN_ATTEMPT=unknown
ARG BUILD_OCI_REVISION=unknown
ARG BUILD_OCI_SOURCE=https://github.com/dutchgeek/mediamasterr
ARG BUILD_OCI_VERSION=unknown
ARG BUILD_REPOSITORY=https://github.com/dutchgeek/mediamasterr
ARG BUILD_DOCKER_IMAGE=ghcr.io/dutchgeek/mediamasterr
ARG BUILD_CONTAINER_DIGEST=unknown
LABEL org.opencontainers.image.title="MediaMasterr" \
	  org.opencontainers.image.description="Media server cleanup and deletion management tool" \
	  org.opencontainers.image.source="${BUILD_REPOSITORY}" \
	  org.opencontainers.image.url="${BUILD_REPOSITORY}" \
	  org.opencontainers.image.version="${BUILD_VERSION}" \
	  org.opencontainers.image.revision="${BUILD_COMMIT_SHA}" \
	  org.opencontainers.image.created="${BUILD_TIMESTAMP}" \
	  org.opencontainers.image.licenses="MIT" \
	  org.opencontainers.image.vendor="DutchGeek"
ENV APP_COMMIT_SHA=${BUILD_COMMIT_SHA} \
	APP_SHORT_SHA=${BUILD_SHORT_SHA} \
	APP_BUILD_TIMESTAMP=${BUILD_TIMESTAMP} \
	APP_DOCKER_TAG=${BUILD_DOCKER_TAG} \
	APP_RELEASE_CHANNEL=${BUILD_RELEASE_CHANNEL} \
	APP_WORKFLOW_RUN_NUMBER=${BUILD_WORKFLOW_RUN_NUMBER} \
	APP_WORKFLOW_RUN_ATTEMPT=${BUILD_WORKFLOW_RUN_ATTEMPT} \
	APP_OCI_REVISION=${BUILD_OCI_REVISION} \
	APP_OCI_SOURCE=${BUILD_OCI_SOURCE} \
	APP_OCI_VERSION=${BUILD_OCI_VERSION} \
	APP_DOCKER_IMAGE=${BUILD_DOCKER_IMAGE} \
	APP_CONTAINER_DIGEST=${BUILD_CONTAINER_DIGEST} \
	APP_DOCKER_DIGEST=${BUILD_CONTAINER_DIGEST} \
	APP_GIT_REPOSITORY=${BUILD_REPOSITORY}
COPY --from=frontend-build /workspace/frontend/dist /app/frontend/dist
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["sh", "-c", \
	"exec granian --interface asgi --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000} backend.api.main:app"]
