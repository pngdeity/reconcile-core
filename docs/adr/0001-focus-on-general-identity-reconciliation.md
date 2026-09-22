# 0001. Focus on general identity reconciliation (P1)

- **Status:** Accepted
- **Date:** 2026-09-21
- **Related:** `docs/CONSOLIDATION-PLAN.md`; ADR-0002, ADR-0003, ADR-0004

## Context

The project began as a modular ETL pipeline to reconcile fragmented social
identities (LinkedIn, Discord, Matrix, generic CSV) into a "pristine Google
Contacts master list" (`docs/RECONCILE-CORE-HANDOFF.md` §0). The consolidation
(Option B) then made a canonical SQLite store the source of truth and added a
domain profile — the Illini Drumline — as a real consumer.

Two propositions now share the repository:

- **P1 — a general, reusable identity-reconciliation engine.** No PII, testable,
  projection-agnostic.
- **P2 — the Illini Drumline data platform.** PII-bearing, domain-specific,
  including Google Groups provisioning.

They need different roadmaps, and the outstanding backlog (the D-series in
`docs/AGENT-ONBOARDING.md` §7) was almost entirely discoverability and
onboarding hygiene: it advanced neither proposition's core capability. The only
dataset with real acceptance criteria belongs to P2, while the stated mission is
P1.

## Decision

- The project's emphasis is **P1**: a general, reusable, zero-loss identity
  reconciliation engine.
- The drumline profile is a **reference consumer and validation corpus**, not
  the product. It receives no roadmap investment; B7 (Google Groups
  provisioning, 181 adds remaining) is **out of scope**.
- The Illini repository is **not archived**; it remains the local PII corpus and
  the source of curated decisions.

## Consequences

- Roadmap priority shifts to engine capability — identity resolution, conflict
  policy, safe apply, ingestion breadth — over domain features.
- Validation must be runnable **without PII**, so a synthetic corpus and golden
  regression harness is a prerequisite for core work (ADR-0004, C4).
- Docs that framed the drumline as the deliverable are demoted to reference
  material; the domain work stays documented but off the critical path.
- The engine's success is measured by being usable on any contact export, not
  by finishing the drumline rollout.
