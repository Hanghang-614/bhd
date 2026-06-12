# BHD Hook Examples

These scripts are thin wrappers around the `bhd-memory hook-*` CLI commands. They are meant to be adapted to Claude Code, Codex, or another tool's hook payload format.

Environment variables:

- `BHD_HOOK_SOURCE_APP`: source name, for example `claude_code_hook` or `codex_hook`
- `BHD_HOOK_SESSION_ID`: external session id
- `BHD_HOOK_PROJECT_PATH`: workspace/project path

Capture a turn:

```bash
./capture-turn.sh user "请记住：当前项目测试命令是 uv run --extra dev pytest -q。"
```

Recall context:

```bash
./recall.sh "当前项目测试命令"
```

Commit a session:

```bash
./commit-session.sh precompact
```

