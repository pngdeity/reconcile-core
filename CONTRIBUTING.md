# Contributing

Foundation conventions live in [AGENTS.md](AGENTS.md) — read it first. What follows is the contributor-facing subset.

## Development Environment

```bash
uv sync          # install dependencies
uv run pytest    # all 47 tests must pass
```

Never edit `pyproject.toml` or `uv.lock` manually. Use `uv add` / `uv add --dev`.

## Adding a Platform Adapter

1. Implement `BaseAdapter.extract(file_path) -> Generator[StandardContact]` in `adapters/<name>.py`
2. Import the class in `adapters/__init__.py` and add to `__all__`
3. Register in `ADAPTER_CLASSES` in `main.py` (use the try/except ImportError pattern)
4. Add `--platform` choice to argparse in `main.py`
5. Add sample data in `test_data/` and tests in `tests/test_adapters.py`

See [docs/ADAPTER_RESEARCH.md](docs/ADAPTER_RESEARCH.md) for roadmaps on Facebook, GitHub, X.com, and Telegram.

## Error Handling

Never swallow errors. Bubble them to the CLI layer:

| Exception | Raise When |
|-----------|------------|
| `GWSCommandError` | Any `gws` subprocess failure |
| `EtagsConflictError` | 412 / etag mismatch on update |
| `sqlite3.Error` | Database operation failure |
| `ValueError` | Malformed input data |

## Git Workflow

- **Always confirm** with maintainer before committing to `main`
- **Signed commits** required: `git commit -S`
- **Semantic messages**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- Never stage `.gemini/` or `.agents/` directories

## Principles

- **Zero-loss**: Never overwrite fields without user confirmation
- **User-space only**: Application data lives in `$XDG_DATA_HOME` — no system-level writes
- **Idempotent**: Running the same extraction twice produces "no changes detected"
- **No PII**: Sample data in `test_data/` must never contain real contact information
