#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export BHD_QDRANT_URL="${BHD_QDRANT_URL:-http://127.0.0.1:6333}"
export BHD_QDRANT_COLLECTION="${BHD_QDRANT_COLLECTION:-bhd_memory}"
export BHD_DB_PATH="${BHD_DB_PATH:-$ROOT_DIR/.bhd/bhd.sqlite}"
export BHD_DATA_DIR="${BHD_DATA_DIR:-$ROOT_DIR/.bhd/data}"
export BHD_HOST="${BHD_HOST:-127.0.0.1}"
export BHD_PORT="${BHD_PORT:-8767}"
export BHD_OPEN_BROWSER="${BHD_OPEN_BROWSER:-1}"

APP_URL="http://${BHD_HOST}:${BHD_PORT}"
if [[ "$BHD_HOST" == "0.0.0.0" || "$BHD_HOST" == "::" ]]; then
  APP_URL="http://127.0.0.1:${BHD_PORT}"
fi

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 1
  fi
}

need_cmd curl
need_cmd uv

mkdir -p "$(dirname "$BHD_DB_PATH")" "$BHD_DATA_DIR"

echo "Checking Qdrant: $BHD_QDRANT_URL"
if ! curl -fsS "$BHD_QDRANT_URL/" >/dev/null; then
  cat >&2 <<EOF
Qdrant is not reachable at $BHD_QDRANT_URL

Start Qdrant first, for example:
  docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant
EOF
  exit 1
fi

echo "Initializing BHD Memory"
uv run bhd-memory init

echo
echo "BHD Memory is starting"
echo "  App:        $APP_URL"
echo "  Qdrant UI:  ${BHD_QDRANT_URL%/}/dashboard"
echo "  Collection: $BHD_QDRANT_COLLECTION"
echo "  SQLite:     $BHD_DB_PATH"
echo "  Data dir:   $BHD_DATA_DIR"
echo

if [[ "$BHD_OPEN_BROWSER" == "1" ]] && command -v open >/dev/null 2>&1; then
  (sleep 2; open "$APP_URL" >/dev/null 2>&1 || true) &
fi

exec uv run bhd-memory serve --host "$BHD_HOST" --port "$BHD_PORT"
