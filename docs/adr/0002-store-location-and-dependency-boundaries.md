# 0002. Store location and dependency boundaries

- **Status:** Accepted
- **Date:** 2026-09-21
- **Related:** `docs/CONSOLIDATION-PLAN.md` §10; `docs/AGENT-ONBOARDING.md` §4

## Context

`docs/CONSOLIDATION-PLAN.md` §10 left several questions open: where the store
lives, whether the Google path stays, what the dependency rule is, and what the
project is called. Phase B4 chose a repo-local `var/contacts.db` "for now" with
the XDG default explicitly deferred. A reusable tool (ADR-0001) must not write
its runtime state into its own checkout, and the model layer has always promised
to stay standard-library only.

## Decision

- **Store path:** the default is the XDG data directory
  (`$XDG_DATA_HOME/reconcile-core/contacts.db`), overridable by `--db` and
  `RECONCILE_CORE_DB`.
- **Repo-local stores:** only the drumline reference profile uses a repo-local
  `var/` store, passed explicitly.
- **Dependencies:** the core layer (`models`, `store`, `reconciler`, `adapters`,
  `io`) stays **stdlib-only**; `rich` is confined to the CLI layer.
- **Name:** the project remains `reconcile-core`.
- **Drumline location:** the profile stays in-repo as a reference consumer
  (ADR-0001), not extracted.

## Consequences

- The current repo-local default is a behavior change and needs a documented
  upgrade path (ADR-0004, C7/D8).
- Configuration becomes a fixed contract to document: `RECONCILE_CORE_DB` and
  `RECONCILE_CORE_DRUMLINE_CONFIG`, plus their defaults. The former "open XDG
  decision" language is removed.
- Any proposed runtime dependency must be justified against the stdlib-only
  core rule; `rich` stays a CLI-only concern.
