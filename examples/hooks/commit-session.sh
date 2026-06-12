#!/usr/bin/env bash
set -euo pipefail

reason="${1:-hook_commit}"

uv run bhd-memory hook-commit \
  --source-app "${BHD_HOOK_SOURCE_APP:-generic_hook}" \
  --session-id "${BHD_HOOK_SESSION_ID:-default}" \
  --reason "$reason"

