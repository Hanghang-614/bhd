#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    codex_runner = Path(__file__).resolve().parents[2] / "codex-plugins" / "bhd-memory" / "scripts" / "bhd_hook.py"
    os.environ.setdefault("BHD_HOOK_SOURCE_APP", "claude_code_hook")
    if not codex_runner.exists():
        print(f"BHD hook runner not found: {codex_runner}", file=sys.stderr)
        return 1
    namespace = {"__name__": "__main__", "__file__": str(codex_runner)}
    code = codex_runner.read_text(encoding="utf-8")
    exec(compile(code, str(codex_runner), "exec"), namespace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

