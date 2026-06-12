# BHD Memory Claude Code Hook Template

This directory contains a Claude Code hook template for BHD Memory. It reuses the local `bhd-memory` CLI and mirrors the same lifecycle used by the Codex sample:

- `UserPromptSubmit`: recall memory and knowledge.
- `Stop`: capture the current turn.
- `PreCompact`: commit the session.
- `SessionEnd`: commit the session.
- `SessionStart`: sweep idle sessions.

Set these environment variables in the shell that launches Claude Code:

```bash
export BHD_QDRANT_URL=http://127.0.0.1:6333
export BHD_HOOK_SOURCE_APP=claude_code_hook
```

The template expects the host to replace `${CLAUDE_PLUGIN_ROOT}` with this directory.

