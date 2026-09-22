# 0004. P1 delivery roadmap

- **Status:** Accepted
- **Date:** 2026-09-21
- **Related:** ADR-0001, ADR-0002, ADR-0003; `docs/AGENT-ONBOARDING.md` §7

## Context

With ADR-0001 (P1 emphasis), ADR-0002 (store and dependency boundaries), and
ADR-0003 (Google as a projection) accepted, the downstream questions collapse.
The prior backlog (D1–D12) was discoverability-centric and could not make the
engine's core chain any stronger: **ingest → resolve identity → merge losslessly
with a deterministic conflict policy → project to a destination.**

This record fixes the delivery order. It uses a `C` series for capability work
and retains the existing `D` numbers for discovery/hygiene.

## Decision — prioritized backlog

### Tier 0 — Decide

- **C0 — Decision record.** The accepted decisions in ADR-0001–0003, plus the
  documentation realignment listed under Consequences.

### Tier 1 — Foundations (protect the asset, prove correctness)

- **C1 — Store backup/restore + snapshot.** The store is a git-ignored PII file
  with no code-level backup path and holds store-native state
  (`external_status`, `decision_state`) that exists nowhere else.
- **C4 — Synthetic no-PII corpus + golden regression harness.** The substrate
  for C2/C3/C5/C6 and for CI; enables work without PII.
- **D6 — CI (`ruff` + `pytest`).** Cheap, locks C4 in. Does **not** require D1 or
  `apm compile`, since tests do not depend on agent context.

### Tier 2 — Core capability (P1's reason to exist)

- **C2 — Identity resolution and merge/split.** Deduplication, confidence, and
  entity merge/split over the store. Absorbs the legacy `fuzzy_match_name()`
  and thereby closes D2 (ADR-0003).
- **C3 — Deterministic conflict truth hierarchy + actionable `resolve`.** The
  headline promise from the handoff. Today `cmd_resolve` (`cli.py:86`) is
  read-only: it lists unresolved identities and exits.
- **C5 — Safe apply.** Rollback, idempotency, and run history from `audit_log`,
  so `--apply` has an undo path. (Rate-limit backoff already exists.)
- **C6 — Ingestion breadth.** vCard and generic CSV profiles; a formal adapter
  extraction contract; scheduling of the social extractors surveyed in
  `docs/ADAPTER_RESEARCH.md`.

### Tier 3 — Reach (make it distributable)

- **C7 — Installable tool.** Console entry points, XDG store default (ADR-0002),
  versioning. Absorbs D7 (config contract) and D9 (`gws` clarity).
- **C8 — Projection interface.** Google and drumline-members become the first
  two implementations of one projection abstraction.
- **D1 — Portable APM context.** Replace the absolute `apm.yml` dependency path;
  affects a clean-machine agent bootstrap only.
- **D3+D4 — Bootstrap and `seed --demo`.** One command for
  `uv sync → migrate → seed → pytest`, P1-shaped; depends on C4 and D1. The
  drumline config-copy step moves to the reference-consumer docs.
- **D8 — Migration guide.** XDG default, upgrade path, and migration-authoring
  rules.

### Tier 4 — Hygiene

- **D5+D11 — Reference-consumer doc** for the drumline profile.
- **D10 — Backlog tracking.** File the stable list as issues or
  `docs/OPEN-ITEMS.md`.
- **D12 — Test-count enforcement.** Trivial; the prose count is already
  de-hardcoded.

### Collapsed, removed, out of scope

- **Removed:** D2 (retired per ADR-0003), D9 (folded into C7).
- **Merged:** D5+D11 → reference-consumer doc; D3+D4 → bootstrap/seed.
- **Out of scope:** B7 (Google Groups provisioning per ADR-0001).

## Dependency graph

```
C4 ─┬─> C2 ─> C3 ─> C5
    ├─> C6
    └─> D3+D4
D1 ────> D3+D4
C7 ────> D8, D3+D4
C1, D6 — independent
```

## Consequences

- **Immediate first actions (the "next agent"):** write this decision record
  (C0); snapshot and back up the current store before refactoring (C1); build
  the synthetic corpus and CI (C4 + D6). Then work C2 → C3 → C5, with C6
  parallelizable.
- **Documentation realignment** is part of C0:
  - `docs/CONSOLIDATION-PLAN.md` B4 note "repo-local `var/`, for now" and the
    deferred XDG decision (superseded by ADR-0002).
  - `docs/AGENT-ONBOARDING.md` bootstrap "copy drumline configs" step (drumline
    is now a reference consumer).
  - `docs/RECONCILE-CORE-HANDOFF.md` §1 `identity_map` / `BasePersistence`
    description (stale: `external_refs` replaced `identity_map`).
- **Success criterion:** a clean clone can bootstrap, exercise the engine on
  no-PII data, and reconcile/resolve conflicts safely without any domain
  profile.
