# Plugin Templates

## Codex

Repo-local sample:

```text
examples/codex-plugins/bhd-memory
```

The manifest is validator-compatible. The hook template is in:

```text
examples/codex-plugins/bhd-memory/hooks/hooks.json
```

The hook runner calls the local `bhd-memory` CLI and supports:

- `recall`: recalls memory and knowledge for prompt submit.
- `capture`: captures user/assistant turns.
- `commit`: commits the active session before compaction.
- `sweep`: commits idle sessions at startup.

Environment:

```bash
export BHD_QDRANT_URL=http://127.0.0.1:6333
export BHD_HOOK_SOURCE_APP=codex_hook
```

Validate:

```bash
uv run --with pyyaml python /Users/hang/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  examples/codex-plugins/bhd-memory
```

## Claude Code

Claude Code hook template:

```text
examples/claude-code-plugin/hooks/hooks.json
```

It reuses the same hook runner and defaults `BHD_HOOK_SOURCE_APP=claude_code_hook`.

