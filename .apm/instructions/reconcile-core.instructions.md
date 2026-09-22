---
description: reconcile-core ETL pipeline conventions
applyTo: "**"
---
# AGENTS.md: `reconcile-core`

ETL pipeline to reconcile social identities (LinkedIn, Discord, Matrix, Generic CSV) into Google Contacts via the `gws` CLI.
**Principle:** Zero-loss reconciliation — never overwrite without user confirmation.
Full spec: `docs/RECONCILE-CORE-HANDOFF.md`.

## Documentation Self-Healing

Trust but verify. Claims in AGENTS.md are **assertions about the codebase**, not guarantees. Before acting on any claim:

1. **Cross-check against source.** If a section says `SubprocessError` but `google_adapter.py` defines `GWSCommandError`, the doc is stale — fix it first.
2. **Modify docs when you modify code.**
   - New adapter? Update the adapter list, `--platform` choices, and test count.
   - New error type? Update the error conventions table.
   - Changed CLI args? Update command examples.
   - Added/removed test files? Update the test count.
3. **Startup checklist** — run these at session open:
   - `rg choices src/reconcile_core/main.py` — does it match the `--platform` list below?
   - `rg "class.*Error" src/reconcile_core/google_adapter.py src/reconcile_core/loader.py` — do error classes match the error conventions table?
   - `uv run pytest --collect-only -q | tail -1` — test count should be ~47.
4. **Context file inventory.** If any of these files are missing or stale, note it:
   - `docs/RECONCILE-CORE-HANDOFF.md` — detailed technical spec.
   - `docs/ADAPTER_RESEARCH.md` — roadmap for Facebook, GitHub, X.com, Telegram.
   - `docs/SETUP.md` — end-user onboarding and prerequisites.
   - `docs/CONSOLIDATION-PLAN.md` — proposed Option B consolidation (normalized store as master).

## Repo-Specific Notes

These override generic inherited guidance that does not apply here:

- **Agent context is generated, not tracked.** `AGENTS.md` (and the `.github/instructions/`, `.agents/skills/` outputs) are produced by APM and are git-ignored. Regenerate with `apm compile` from `.apm/instructions/` plus the `development-practices` package. Do not hand-edit generated files.
- **No `upstream` remote.** This repo's only remote is `origin`. Ignore generic "upstream-first" / `git refresh` / `upstream/master` guidance.
- **Plan documents live in-repo under `docs/`.** The inherited `~/.gemini/PLANS.md` path is machine-specific; use `docs/` instead (see `docs/CONSOLIDATION-PLAN.md`).
- **Only `AGENTS.md` exists as agent context.** There are no `CONTEXT.md`, `GEMINI.md`, `CLAUDE.md`, or `.codex`/`CODEX.md` files here.
- **Use `rg` and `fd`.** `grep` is unavailable/denied in some agent environments.

## Quick Start

```bash
uv sync                                          # install dependencies
uv run pytest                                    # full test suite (47 tests)
uv run pytest tests/test_adapters.py -k test_linkedin  # single test
uv run python -m reconcile_core.main --help      # CLI usage
```

```bash
uv run python -m reconcile_core.main <file> -p <linkedin|discord|matrix|generic> [--dry-run]
```

## Project Structure

| File | Purpose |
|------|---------|
| `models.py` | `StandardContact`, `SocialHandle`, `ReconciliationDiff` — shared vocabulary, stdlib only |
| `interfaces.py` | `BaseAdapter(ABC)`, `BasePersistence(ABC)` — contracts |
| `database.py` | `SQLitePersistence` — store-backed persistence (platform identity -> entity via `external_refs`; `audit_log`, `unresolved_identities`) |
| `google_adapter.py` | `GoogleAdapter` — wraps `gws` via `subprocess`; `GWSCommandError` |
| `loader.py` | `ContactLoader.apply_additions()` — PATCH contacts; `EtagsConflictError` |
| `reconciler.py` | `Reconciler.reconcile()` — normalization-aware diff for emails, urls, handles, imClients, phones |
| `main.py` | CLI loop; `ADAPTER_CLASSES` registry; `fuzzy_match_name()` |
| `adapters/` | `LinkedInAdapter`, `DiscordAdapter`, `MatrixAdapter`, `GenericCSVAdapter` |
| `store/` | Canonical contacts store (source of truth): `migrations/*.sql`, `migrate.py` runner, `store.py` helpers, `labels.py` vocabulary, `bridge.py` (StandardContact <-> store) |
| `io/` | Google Contacts CSV projection: `google_csv.py` (`import_contacts`, `export_contacts`) |
| `test_data/` | Sample files for each adapter (no PII) |
| `tests/` | Test files mirror `src/reconcile_core/` structure |

## Error Conventions

| Exception | Module | Raised When |
|-----------|--------|-------------|
| `GWSCommandError` | `google_adapter.py` | Any `gws` subprocess failure (wraps `CalledProcessError` or `FileNotFoundError`) |
| `EtagsConflictError` | `loader.py` | 412 Precondition Failed / etag mismatch on contact update (subclass of `GWSCommandError`) |
| `sqlite3.Error` | `database.py` | Database operation failure — caught in `_connection()`, triggers rollback |
| `ValueError` | adapter files | Malformed input (missing LinkedIn header, invalid JSON format, CSV without name column) |

Never swallow errors. Bubble them to the CLI layer (`main.py`) for user reporting.

## Adapter Contract

To add a new platform adapter:
1. Implement `BaseAdapter.extract(file_path: Path) -> Generator[StandardContact]` in `adapters/<name>.py`
2. Import and add the class to `adapters/__init__.py` and its `__all__` list
3. Register in `ADAPTER_CLASSES` dict in `main.py` (with try/except ImportError pattern for graceful fallback)
4. Add `--platform` choice to argparse in `main.py`
5. Add sample data in `test_data/` and tests in `tests/test_adapters.py`

## Git Workflow

- **Confirm** with user before committing to `main`
- **Mandatory signed commits:** `git commit -S`
- **Semantic commit messages:** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- **Never stage** `.gemini/` or `.agents/` directories

## Test Conventions

- Framework: `pytest` with `tmp_path` fixture for temporary files
- Naming: `tests/test_<module>.py` mirrors `src/reconcile_core/<module>.py`
- Sample data: `test_data/` directory — no PII, no real contact info
- All tests must pass before any change is considered complete

## Known Limitations

- **Stale-write risk:** Loader sends full merged field lists on update — a field added by another client between fetch and PATCH may be clobbered. Etag guards whole-contact conflicts only.
- **Handles not reconciled:** `SocialHandle` field in `StandardContact` exists but is not processed by `Reconciler.reconcile()` or displayed in the CLI diff table.
- **Discord adapter:** Returns empty generator on JSON parse errors rather than raising `ValueError` — silent data loss possible.
