#!/usr/bin/env bash
set -euo pipefail

query="${1:?query is required}"

args=(
  "$query"
  --source-app "${BHD_HOOK_SOURCE_APP:-generic_hook}"
  --session-id "${BHD_HOOK_SESSION_ID:-default}"
)

if [[ -n "${BHD_HOOK_PROJECT_PATH:-}" ]]; then
  args+=(--project-path "$BHD_HOOK_PROJECT_PATH")
fi

uv run bhd-memory hook-recall "${args[@]}"
