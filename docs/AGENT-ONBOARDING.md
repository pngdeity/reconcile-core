# Agent Onboarding & Discovery Guide

**Audience:** an AI agent (or developer) starting work inside `reconcile-core`
only, with no prior context.
**Purpose:** get you productive in minutes, tell you what you must not break,
and hand you a concrete backlog for closing the remaining discovery gaps.

> Trust but verify. Every command and claim here is checkable; if code and this
> doc disagree, the code wins, and fixing the doc is part of your change.

---

## 0. 30-second orientation

`reconcile-core` reconciles fragmented social identities (LinkedIn, Discord,
Matrix, generic CSV) into a **canonical SQLite contacts store**. The store is the
source of truth; Google Contacts is one more adapter/projection, not the master.

Two CLI surfaces exist:

| Surface | Command | Status |
| --- | --- | --- |
| Unified (preferred) | `python -m reconcile_core <command>` | current |
| Drumline profile | `python -m reconcile_core.profile.drumline <command>` | current (domain profile) |

Command reference:

```bash
# Unified CLI (store-first)
uv run python -m reconcile_core migrate [--profile drumline] [--status]
uv run python -m reconcile_core backup [--out FILE]
uv run python -m reconcile_core restore SNAPSHOT [--force]
uv run python -m reconcile_core ingest EXPORT -p <linkedin|discord|matrix|generic>
uv run python -m reconcile_core resolve
uv run python -m reconcile_core duplicates [--min-score 0.5]
uv run python -m reconcile_core merge SOURCE TARGET [--reason TEXT]
uv run python -m reconcile_core split ENTITY [--ref SOURCE:VALUE] [--point ID] [--name NAME]
uv run python -m reconcile_core reconcile EXPORT -p <platform> [--apply]
uv run python -m reconcile_core export google-contacts --out DIR
uv run python -m reconcile_core export drumline-members --out FILE
uv run python -m reconcile_core audit

# Drumline profile
uv run python -m reconcile_core.profile.drumline migrate
uv run python -m reconcile_core.profile.drumline import-drumline --tracker TRACKER.csv
uv run python -m reconcile_core.profile.drumline audition-members
uv run python -m reconcile_core.profile.drumline idl-roster
uv run python -m reconcile_core.profile.drumline import-master   --input LEGACY-MASTER.csv
uv run python -m reconcile_core.profile.drumline name-resolutions
uv run python -m reconcile_core.profile.drumline export-members  --out MEMBERS.csv
uv run python -m reconcile_core.profile.drumline needs-live-email --out NEEDS-LIVE-EMAIL.csv
```

Full design: `docs/CONSOLIDATION-PLAN.md` (phases B0–B7 and the phase log in §13).

---

## 1. Bootstrap: make it runnable

A fresh clone is **inert**: agent context, the store, and the drumline configs are
all git-ignored. Do these in order.

```bash
cd <reconcile-core>                 # e.g. ~/repos/pngdeity/incubating/reconcile-core

# 1. Agent context (AGENTS.md is generated, not tracked)
apm compile                         # APM CLI (gap D1); not required to build or test

# 2. Dependencies + test baseline
uv sync
uv run pytest -q                    # all tests pass

# 3. Create/refresh the store
uv run python -m reconcile_core migrate
uv run python -m reconcile_core migrate --profile drumline   # adds the drumline overlay

# 4. Snapshot the store (writes <store-dir>/backups/)
uv run python -m reconcile_core backup
```

### Getting data into the store

The real store is git-ignored at `var/contacts.db`. Two options:

**Option A — import the real legacy store** (cross-repo; contains PII, stays local):

```bash
ILL=~/repos/pngdeity/active/illini-drumline-contacts-alumni
uv run python -m reconcile_core.store.import_db --source "$ILL/working/contacts.db"
```

This re-stamps `schema_version` to this package's baseline and leaves unowned
tables (e.g. `drumline_outreach`) as pending migrations. See §3.

**Option B — start empty.** `migrate` already gives you a usable store; load an
adapter export with `ingest` (see the command reference in §0); the bundled
no-PII sample works out of the box:
`uv run python -m reconcile_core ingest test_data/generic_sample.csv -p generic`.

### Drumline profile configs (PII, git-ignored)

`var/drumline/` must contain the curated configs. Copy them from the illini repo:

```bash
mkdir -p var/drumline
ILL=~/repos/pngdeity/active/illini-drumline-contacts-alumni
cp "$ILL"/working/{manual_entity_merges,manual_name_resolutions,manual_address_map,group_invite_required,group_blocked,group_hold}.json var/drumline/
```

`audition_members.json` (audition-results names) and `idl_roster.json` (beatrack
IDL historical roster) must also be present in `var/drumline/`; they are produced
by the illini-side tooling and are **not** in the copy set above.

Without these, profile commands succeed but produce empty/incorrect output — add
the `config --check` guard (gap D4).

### Drumline refresh order (do not reorder)

```bash
ILL=~/repos/pngdeity/active/illini-drumline-contacts-alumni
P="python -m reconcile_core.profile.drumline"
uv run $P migrate            # same overlay as `migrate --profile drumline`
uv run $P import-drumline --tracker "$ILL/deliverables/Tracker.csv"
uv run $P audition-members
uv run $P idl-roster
uv run $P import-master   --input   "$ILL/working/backups/drumline-master-v2_pre_rename_20260921.csv"
uv run $P name-resolutions
uv run $P export-members  --out     /tmp/drumline-members.csv
uv run $P needs-live-email --out    /tmp/group_needs_live_email.csv
```

`import-master` **overwrites** the `drumline_outreach` overlay, so it must run
before `name-resolutions`. Its `--input` is the **legacy** `drumline-master-v2`
seed (the dated backup is the surviving copy); `drumline-members.csv` is an
*output* of the store, not an input, so it cannot be used here. See §3.

---

## 2. System map

| Path | Responsibility |
| --- | --- |
| `models.py` | `StandardContact`, `SocialHandle`, `ReconciliationDiff` (stdlib only) |
| `interfaces.py` | `BaseAdapter`, `BasePersistence` contracts |
| `store/` | Canonical store: `migrations/*.sql`, `migrate.py` runner, `store.py` helpers, `labels.py` vocabulary, `bridge.py` (`StandardContact` ↔ store), `identity.py` (duplicate detection + lossless merge/split), `import_db.py` (legacy import), `backup.py` (snapshot/restore/verify) |
| `io/` | Google Contacts CSV projection: `google_csv.py` (`import_contacts`, `export_contacts`) |
| `reconciler.py` | Normalization-aware union: emails, urls, handles, imClients, phones |
| `database.py` | `SQLitePersistence` (store-backed `BasePersistence` + `ingest`/`contact_from_entity`) |
| `google_adapter.py` / `loader.py` | `gws` wrapper / etag-guarded PATCH (Google projection only) |
| `cli.py` + `__main__.py` | Unified CLI: `migrate`, `backup`, `restore`, `ingest`, `resolve`, `duplicates`, `merge`, `split`, `reconcile`, `export`, `audit` |
| `profile/drumline/` | Illini Drumline profile: overlay migration, importers, name resolutions, member export, config |
| `adapters/` | LinkedIn, Discord, Matrix, Generic CSV; `ADAPTER_CLASSES` registry (legacy `main.py` retired — ADR-0003) |
| `test_data/corpus/` | No-PII golden corpus (C4) driving `tests/test_corpus.py`: multi-platform convergence, idempotency, collision surfacing, Google projection round-trip |

Store schema (entities · external_refs · contact_points · addresses · aliases ·
segments · segment_members · decision_state · external_status · audit_log ·
unresolved_identities) is defined in
`src/reconcile_core/store/migrations/0001_init.sql`; the drumline overlay is in
`src/reconcile_core/profile/drumline/migrations/0002_drumline_outreach.sql`; and
`0003_repair_schema.sql` recreates `audit_log`/`unresolved_identities` for stores
imported by `import_db` (which re-stamps `schema_version` without running
`0001_init.sql`).

---

## 3. Invariants you must not break

1. **The store is master.** Never hand-edit generated outputs (`Contacts.csv`,
   `Contacts_import.csv`, `drumline-members.csv`); change the store and regenerate.
2. **Zero loss / Contact-Completeness.** Union additions; never delete a contact
   point to resolve a conflict. Verification only orders/labels, never prunes.
3. **Identity = `external_refs`.** A `(source, ref_value)` pair maps to exactly one
   entity; one entity may hold many platform refs (cross-platform convergence).
   Do not reintroduce an `identity_map`.
4. **The alumni marker** is `Custom Field 1 = ("Alumni Status", "Illini Drumline")`
   and the `illini-drumline-alumni` segment; it is reconstructed on export, not
   stored as a handle.
5. **Curated decisions are data, not code.** The three name resolutions, the
   Rachel Misurac entity merge, and verification overrides live in
   `var/drumline/*.json` and the store. Preserve them.
6. **Profile refresh order:** migrations → import-drumline → audition-members →
   idl-roster → **import-master** → name-resolutions → export-members →
   needs-live-email (§1).
7. **Migration rules:** the runner owns `schema_version`; migrations must not
   contain `BEGIN`/`COMMIT`; profile migrations use `CREATE TABLE IF NOT EXISTS`
   because imported legacy DBs carry unowned tables; profile migration dirs are
   passed via `extra_dirs`.
8. **PII stays out of git.** See §4.

---

## 4. Data & PII boundaries

- **Git-ignored (keep local):** `var/` (store + drumline configs), `AGENTS.md`
  and other generated context, `*.db-wal`/`*.db-shm`, `.venv`.
- **Never commit** real contact data, configs, or generated projections.
- **Real data lives in the illini repo**
  (`~/repos/pngdeity/active/illini-drumline-contacts-alumni`): `working/contacts.db`,
  `working/*.json` configs, `deliverables/*.csv`. That project is **not archived**;
  it remains the source of the legacy store and curated configs.
- `test_data/` must stay no-PII.

---

## 5. Dev loop & definition of done

```bash
uv run pytest -q                 # all tests pass
uv run ruff check src tests      # must be clean
apm compile                      # if you touched .apm/instructions/**
```

A change is complete when: tests pass, lint is clean, docs you invalidated are
fixed, and (repo policy) commits are signed (`git commit -S`) with a
semantic message. CI (`.github/workflows/ci.yml`) runs the same lint and test
commands on push/PR; pushing still requires confirmation.

---

## 6. Existing open decisions & backlog

Settled by `docs/adr/` (ADR-0001–0004):

- **§10 decisions:** all resolved — `gws` is an optional writer (ADR-0003); the
  store is XDG-default with `--db` (ADR-0002); core stays stdlib-only
  (ADR-0002); the name stays `reconcile-core` (ADR-0002); the drumline is an
  in-repo reference consumer (ADR-0001); illini is not archived.
- **Illini-side Google Groups:** the add/invite campaign is **complete** (Sep 23,
  2026) — 421 group entries, 0 remaining in the run lists, 3 addresses silently
  refused by Google plus 1 invite accepted under a different address
  (`gmkwain@aol.com` -> `gmkwain1@gmail.com`, now stored) and 1 blocked (illini
  `working/group_blocked.json`). Still
  outside reconcile-core's roadmap (ADR-0001); live details in the illini `TODO.md`.
- **Illini-side:** the `working/*.json` maps cleanup (recorded in the illini TODO).

---

## 7. Discovery gaps to close (your backlog)

Each item removes a future agent's discovery cost. Suggested order is top-down;
work in small signed commits and update this doc as you go.

| ID | Goal | Acceptance criteria | Effort |
| --- | --- | --- | --- |
| **D1** | Portable agent context | `apm.yml` dependency resolves via a portable git ref (or vendored package), not an absolute path; `apm compile` works on a clean machine; README documents it as step 0 | M |
| **D2** | One CLI entry point | **Done (C2, ADR-0004):** legacy `main.py` user-facing entry retired; `ADAPTER_CLASSES` lives in `adapters/` | S |
| **D3** | One-command bootstrap | `scripts/bootstrap.sh` (or Makefile) runs `uv sync → apm compile → migrate → seed demo → pytest`; `docs/DATA.md` documents store provenance + the illini copy command | M |
| **D4** | No-PII demo seed | `seed --demo` loads a synthetic store from `test_data/`; `profile.drumline config --check` fails loudly on missing configs; example config template bundled | M |
| **D5** | Capture domain invariants | No-PII `docs/PROVENANCE.md` (or profile README section) documenting §3 items with cross-repo pointers; `profile.drumline refresh` runs the ordered pipeline in code | M |
| **D6** | CI **(done)** | GitHub Actions job runs `ruff check` + `pytest` on push/PR; badge in README | S |
| **D7** | Configuration reference | Document `RECONCILE_CORE_DB`, `RECONCILE_CORE_DRUMLINE_CONFIG`, and default paths (fixed by ADR-0002) | S |
| **D8** | Migration guide | `docs/MIGRATIONS.md` (or store README section): authoring rules, `extra_dirs`, baseline re-stamp rationale, `IF NOT EXISTS` requirement | S |
| **D9** | `gws` clarity | README states the unified path needs no `gws` unless syncing to Google | S |
| **D10** | Backlog tracking | Convert §6 open decisions + this table into GitHub issues (or `docs/OPEN-ITEMS.md`) as the single backlog | S |
| **D11** | Cross-repo pointer | README links the illini project as the data/PII source and explains the profile relationship | S |
| **D12** | Self-healing enforcement | Avoid hardcoded test counts in docs (or add a test asserting the README count matches `pytest --collect-only`) | S |

> **Authoritative sequencing:** `docs/adr/0004-p1-delivery-roadmap.md` supersedes
> this table for ordering. It removes D2 and D9 (ADR-0003 / C7), merges D5+D11
> and D3+D4, and adds the C-series capability items (C1–C8).

**Definition of done for the backlog:** a clone on a clean machine can run the
bootstrap (D1/D3/D6), exercise the system without PII (D4), and a new agent can
learn the invariants without leaving this repo (D5/D7/D8/D10/D11).

---

## 8. Pointers

- `README.md` — usage and architecture overview.
- `CONTRIBUTING.md` — how to regenerate agent context.
- `docs/CONSOLIDATION-PLAN.md` — design, phases, decisions, phase log.
- `docs/adr/` — architecture decision records: authoritative direction (P1 focus, store/dependency boundaries, Google-as-projection) and the delivery roadmap.
- `docs/RECONCILE-CORE-HANDOFF.md` — original design spec; partially superseded (the ADRs win, per its banner).
- `docs/ADAPTER_RESEARCH.md` — platform roadmap (Facebook, GitHub, X.com, Telegram).
- `docs/SETUP.md` — prerequisites (`uv`, `gws`, Python 3.14).
- `src/reconcile_core/profile/drumline/README.md` — profile usage and PII conventions.
