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
export BHD_BUILD_FRONTEND="${BHD_BUILD_FRONTEND:-auto}"

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

build_frontend() {
  local frontend_dir="$ROOT_DIR/frontend"
  local static_index="$ROOT_DIR/src/bhd_memory/api/static/index.html"
  local should_build=0

  [[ -d "$frontend_dir" ]] || return 0

  case "$BHD_BUILD_FRONTEND" in
    0|false|False|FALSE|no|No|NO)
      return 0
      ;;
    1|true|True|TRUE|yes|Yes|YES)
      should_build=1
      ;;
    auto)
      if [[ ! -f "$static_index" ]]; then
        should_build=1
      elif find "$frontend_dir" \
        -path "$frontend_dir/node_modules" -prune -o \
        -type f \( -name '*.js' -o -name '*.jsx' -o -name '*.css' -o -name '*.html' -o -name 'package.json' -o -name 'vite.config.js' \) \
        -newer "$static_index" -print -quit | grep -q .; then
        should_build=1
      fi
      ;;
    *)
      echo "Unsupported BHD_BUILD_FRONTEND=$BHD_BUILD_FRONTEND. Use auto, 1, or 0." >&2
      exit 1
      ;;
  esac

  if [[ "$should_build" == "1" ]]; then
    need_cmd npm
    echo "Building React frontend"
    (
      cd "$frontend_dir"
      if [[ -f package-lock.json ]]; then
        npm ci
      else
        npm install
      fi
      npm run build
    )
  fi
}

build_frontend

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
