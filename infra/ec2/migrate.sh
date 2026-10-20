#!/usr/bin/env bash
set -euo pipefail

WORK_DIR="/opt/clickpe/migrate"
CA_PATH="/opt/clickpe/global-bundle.pem"
IMAGE="clickpe-migrate:local"
PG8000_VERSION="1.31.5"
DB_PORT_VALUE="5432"

build_image() {
  sudo docker build -q -t "$IMAGE" - >/dev/null <<DOCKERFILE
FROM python:3.12-slim
RUN pip install --no-cache-dir pg8000==${PG8000_VERSION}
WORKDIR /app
DOCKERFILE
}

run_migrations() {
  sudo -E docker run --rm \
    -e DB_HOST -e DB_NAME -e DB_USER -e DB_PASSWORD \
    -e DB_PORT="$DB_PORT_VALUE" \
    -e DB_SSLROOTCERT=/ca.pem \
    -v "$CA_PATH:/ca.pem:ro" \
    -v "$WORK_DIR/db:/app/db:ro" \
    "$IMAGE" python -m db.migrate --seed
}

: "${DB_HOST:?}" "${DB_NAME:?}" "${DB_USER:?}" "${DB_PASSWORD:?}"
build_image
run_migrations
