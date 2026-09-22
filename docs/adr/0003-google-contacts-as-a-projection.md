# 0003. Google Contacts is a projection; retire the legacy Google-API entry

- **Status:** Accepted
- **Date:** 2026-09-21
- **Related:** ADR-0001, ADR-0002, ADR-0004

## Context

The original vision made Google Contacts the master list
(`docs/RECONCILE-CORE-HANDOFF.md` §0). The consolidation inverted that: the
canonical SQLite store is authoritative and Google Contacts is one projection.
Two Google paths exist as a result:

1. the unified store-first path (`reconcile`/`export`, `cli.py`), and
2. the legacy Google-API loop (`python -m reconcile_core.main`), which also
   holds the only name-matching helper, `fuzzy_match_name()` (`main.py:40`).

With `gws` now an optional writer, the legacy loop duplicates capability the
unified path already covers.

## Decision

- **`gws` is retained as an optional writer/projection.** The store is
  authoritative; the engine works without `gws`.
- **The user-facing legacy entry point (`python -m reconcile_core.main`) is
  retired** rather than re-exposed as a subcommand.
- **Name matching moves into store-side identity resolution.** The
  `fuzzy_match_name()` capability is absorbed into the resolution work
  (ADR-0004, C2) and must be tested against the synthetic corpus.
- **`google_adapter.py` / `loader.py` remain** as the Google projection module.

## Consequences

- The "one CLI entry point" discovery item (D2) is resolved by removal, not by
  adding a subcommand.
- Docs simplify: `gws` becomes conditional — needed only to sync to Google.
  This absorbs the standalone "`gws` clarity" item (D9).
- Identity resolution gains the orphaned matcher, which removes the last unique
  responsibility of `main.py`.
- README/SETUP references to the legacy loop are removed when the retirement
  lands.
