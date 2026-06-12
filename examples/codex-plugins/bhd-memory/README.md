# BHD Memory Codex Plugin

This is a repo-local Codex plugin sample for BHD Memory. The manifest is kept compatible with the current Codex plugin validator. The `hooks/hooks.json` file is included as the lifecycle hook template to copy into a host that supports hook declarations:

- `UserPromptSubmit`: recall memory and knowledge.
- `Stop`: capture recent turns.
- `PreCompact`: commit the active hook session.
- `SessionStart`: sweep idle sessions.

The hook runner reads JSON payload from stdin when the host provides it, and also accepts environment fallbacks.

## Required Environment

```bash
export BHD_QDRANT_URL=http://127.0.0.1:6333
export BHD_HOOK_SOURCE_APP=codex_hook
```

Optional:

```bash
export BHD_MEMORY_BIN=bhd-memory
export BHD_HOOK_RECALL_LIMIT=6
export BHD_HOOK_IDLE_SECONDS=1800
```

## Local Smoke

```bash
echo '{"session_id":"demo","prompt":"当前项目测试命令是什么？"}' \
  | python3 scripts/bhd_hook.py recall
```
