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
uv run python -m reconcile_core.main Connections.csv --platform linkedin
```

Preview changes without writing:

```bash
uv run python -m reconcile_core.main Connections.csv --platform linkedin --dry-run
```

All platforms:

```bash
uv run python -m reconcile_core.main data.json -p discord
uv run python -m reconcile_core.main matrix.json -p matrix
uv run python -m reconcile_core.main contacts.csv -p generic
```

## Operation

1. **Extract** — Adapters parse platform-specific exports into a common `StandardContact` model
2. **Map** — SQLite identity map links platform IDs to Google `resourceName` values, with fuzzy name matching fallback
3. **Diff** — Normalization-aware comparison detects new emails, URLs, IMs, and phone numbers to add; display name conflicts require manual resolution
4. **Apply** — Safe PATCH updates with etag-based concurrency control

## Architecture

```
adapters/   -->  reconciler.py  -->  loader.py  -->  google_adapter.py  -->  gws CLI
                    |                                        |
               database.py                              Google Contacts
```
