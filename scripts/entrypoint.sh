#!/bin/sh
set -eu

export PORT="${PORT:-8080}"
export UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

exec uvicorn gateway.app:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${UVICORN_WORKERS}"
