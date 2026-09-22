# reconcile-core

ETL pipeline to reconcile fragmented social identities into Google Contacts.

Takes exports from LinkedIn, Discord, Matrix, or generic CSV sources, compares
them against your Google Contacts, and applies safe additions with manual
conflict resolution — never overwriting without your confirmation.

## Supported platforms

| Platform | Source Format | Adapter |
|----------|-------------|---------|
| LinkedIn | `Connections.csv` | `LinkedInAdapter` |
| Discord | `relationships.json` | `DiscordAdapter` |
| Matrix | JSON (m.direct or simple list) | `MatrixAdapter` |
| Generic CSV | Any CSV with name column | `GenericCSVAdapter` |

## Prerequisites

- **Python 3.14+** with [uv](https://docs.astral.sh/uv/)
- **[gws](https://github.com/nickvourd/gws)** CLI authenticated to Google (`gws auth login`)

## Quick start

```bash
uv sync
uv run python -m reconcile_core --help          # unified CLI
```

The store (`var/contacts.db`) is the source of truth:

```bash
uv run python -m reconcile_core migrate [--profile drumline] [--status]
uv run python -m reconcile_core ingest Connections.csv -p linkedin
uv run python -m reconcile_core reconcile Connections.csv -p linkedin         # dry run
uv run python -m reconcile_core reconcile Connections.csv -p linkedin --apply
uv run python -m reconcile_core export google-contacts --out out/
uv run python -m reconcile_core audit
```

Legacy Google-API reconcile path (still supported):

```bash
uv run python -m reconcile_core.main Connections.csv --platform linkedin
uv run python -m reconcile_core.main Connections.csv --platform linkedin --dry-run
uv run python -m reconcile_core.main data.json -p discord
uv run python -m reconcile_core.main matrix.json -p matrix
uv run python -m reconcile_core.main contacts.csv -p generic
```

## Operation

1. **Extract** — Adapters parse platform-specific exports into a common `StandardContact` model
2. **Map** — platform IDs resolve to store entities via `external_refs` (the Google `resourceName` is one more ref), with fuzzy name matching fallback
3. **Diff** — Normalization-aware comparison detects new emails, URLs, IMs, and phone numbers to add; display name conflicts require manual resolution
4. **Apply** — Safe PATCH updates with etag-based concurrency control

## Architecture

```
adapters/   -->  reconciler.py  -->  loader.py  -->  google_adapter.py  -->  gws CLI
                    |                                        |
               database.py                              Google Contacts
```

## Agent context (APM)

Agent instructions are managed by [APM](https://github.com/pngdeity/apm-user-repository) and are **generated, not tracked**:

- Sources: `.apm/instructions/reconcile-core.instructions.md` (this repo) plus the `development-practices` APM package.
- Generated outputs (git-ignored): `AGENTS.md`, `.github/instructions/*`, `.agents/skills/*`.

Regenerate after pulling or changing instructions:

```bash
apm compile
```
