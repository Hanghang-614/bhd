# Contributing

Thanks for helping improve BHD Memory.

## Development Setup

Install dependencies:

```bash
uv sync --extra dev
```

Run checks before opening a pull request:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest -q
```

## Pull Requests

- Keep changes focused and explain the user-facing behavior.
- Add or update tests when changing parsing, retrieval, memory governance, API routes, or persistence.
- Update documentation when a command, configuration option, API shape, or workflow changes.
- Do not commit local databases, transcript archives, `.env` files, virtual environments, or cloned reference repositories.

## Issues

When reporting a bug, include:

- The command or API request you ran.
- The expected behavior.
- The actual behavior and traceback or response body.
- Your Python version and operating system.

For security reports, follow [SECURITY.md](SECURITY.md).
