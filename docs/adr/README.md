# Architecture Decision Records

This directory records the significant, hard-to-reverse decisions behind
`reconcile-core`, in [ADR](https://adr.github.io/) style: Title, Status, Date,
Context, Decision, Consequences.

- One decision per record, numbered `NNNN-kebab-title.md`.
- Statuses: `Proposed`, `Accepted`, `Deprecated`, `Superseded by NNNN`.
- Records are immutable once accepted; change a decision by superseding it.
- Reference these records from code and docs by number (e.g. "ADR-0002").

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-focus-on-general-identity-reconciliation.md) | Focus on general identity reconciliation (P1) | Accepted |
| [0002](0002-store-location-and-dependency-boundaries.md) | Store location and dependency boundaries | Accepted |
| [0003](0003-google-contacts-as-a-projection.md) | Google Contacts is a projection; retire the legacy Google-API entry | Accepted |
| [0004](0004-p1-delivery-roadmap.md) | P1 delivery roadmap | Accepted |

## Context

These records continue the work in `docs/CONSOLIDATION-PLAN.md` (phases B0–B6
and the phase log in §13). The consolidation established a canonical SQLite
store as the source of truth; these ADRs settle the project's direction and
boundaries on top of it.
