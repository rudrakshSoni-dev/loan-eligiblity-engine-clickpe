#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="docker.n8n.io/n8nio/n8n:2.44.4"
NAME="n8n-import-check-$$"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name "$NAME" -e N8N_DIAGNOSTICS_ENABLED=false "$IMAGE" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$NAME" wget -q -O /dev/null http://127.0.0.1:5678/healthz 2>/dev/null; then
    break
  fi
  sleep 2
done

for file in "$ROOT"/n8n/workflows/*.json; do
  docker cp "$file" "$NAME:/tmp/$(basename "$file")"
  docker exec "$NAME" n8n import:workflow --input="/tmp/$(basename "$file")"
done

docker exec "$NAME" n8n export:workflow --all --output=/tmp/all.json >/dev/null
docker exec "$NAME" sh -c "grep -o '\"name\": *\"[A-C] · [^\"]*\"' /tmp/all.json | sort -u"
