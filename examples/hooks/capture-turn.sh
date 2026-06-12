#!/usr/bin/env bash
set -euo pipefail

role="${1:?role is required}"
content="${2:?content is required}"

args=(
  --source-app "${BHD_HOOK_SOURCE_APP:-generic_hook}"
  --session-id "${BHD_HOOK_SESSION_ID:-default}"
  --role "$role"
  --content "$content"
)

if [[ -n "${BHD_HOOK_PROJECT_PATH:-}" ]]; then
  args+=(--project-path "$BHD_HOOK_PROJECT_PATH")
fi

uv run bhd-memory hook-capture "${args[@]}"
