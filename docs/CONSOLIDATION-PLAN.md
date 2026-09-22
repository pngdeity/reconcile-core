# CONSOLIDATION-PLAN.md — Option B: `reconcile-core` as the umbrella

**Status:** proposed (not started)
**Created:** 2026-09-21
**Origin:** Illini Drumline contacts project (`~/repos/pngdeity/active/illini-drumline-contacts-alumni`)
decentered from its deadline; its normalized SQLite store is proposed as the
master data layer for `reconcile-core`.

## 1. Baseline facts

- `reconcile-core` is Python **3.14** (installed: 3.14.7), deps = `rich` only, MIT.
- `gws` CLI present at `/usr/bin/gws`.
- `AGENTS.md` is **APM-generated** from `.apm/instructions/` — edit the sources and run `apm compile`, never hand-edit.
- Local branch is **1 commit behind** `origin/main` (`c770245 Update README.md`).
- Existing persistence: `SQLitePersistence` (`identity_map`, `audit_log`, `unresolved_identities`) at `$XDG_DATA_HOME/reconcile-core/identities.db`.

## 2. Target architecture

```
platform exports ──► adapters/*.extract() ──► StandardContact
                                                   │
                                                   ▼
                                        store_writer / identity resolution
                                                   │
                                                   ▼
   ┌──────────────────────────  SQLite store (MASTER)  ──────────────────────────┐
   │ entities · external_refs · contact_points · addresses · aliases ·          │
   │ segments · segment_members · decision_state · audit_log                    │
   └────────────────────────────────────────────────────────────────────────────┘
                                                   │
                        ┌──────────────────────────┼───────────────────────────┐
                        ▼                          ▼                           ▼
             export_google_contacts        gws destination (optional)     domain profiles
             (CSV: Contacts.csv/import)    (People API via gws,           (drumline segment,
                                            store-authoritative push)      group provisioning)
```

**Core principle change:** Google Contacts stops being the master. It becomes a
**destination/source adapter**, exactly like LinkedIn. The store is
authoritative — which also aligns `reconcile-core`'s "zero-loss" principle with
the illini project's **Contact-Completeness** principle.

## 3. Port map (what moves where)

| From | To `reconcile-core` | Notes |
|---|---|---|
| illini `contacts_store.py`, `labels.py`, `apply_hygiene.py`, `db/*` | `src/reconcile_core/store/` | generic core |
| illini `import_contacts.py`, `export_google_contacts.py` | `src/reconcile_core/io/google_csv.py` | CSV ingest/export |
| illini `audit_state.py`, `audit_integrity.py` | `src/reconcile_core/audit.py` + CLI | generic checks |
| reconcile-core `models.py`, `interfaces.py` | keep | already the shared vocabulary |
| reconcile-core `adapters/*` | keep; add `google_csv` + future FB/GitHub/X/Telegram | adapters now write to the store |
| reconcile-core `database.py` | **replace** with store-backed persistence | `identity_map` -> `external_refs` |
| reconcile-core `reconciler.py` | port to operate on store records; **add handles** | fixes its known gap |
| reconcile-core `google_adapter.py`, `loader.py` | keep as the optional `gws` destination | direction reversed (store -> Google) |
| illini `import_drumline.py`, `export_drumline_members.py`, `import_master.py`, `apply_name_resolutions.py`, `build_address_resolution.py`, `import_group_status.py`, `build_group_lists.py` | `profile/drumline` module | domain module |
| illini `drumline-context/browser-approach/` (Playwright) | out of scope for the core; own module/tool | different concern (group membership automation) |

Roughly **half the illini code is generic and ports nearly verbatim**; the other
half becomes a profile.

## 4. Schema & model changes

- **Adopt the illini store schema** (a superset): `entities`, `external_refs`,
  `contact_points`, `addresses`, `aliases`, `segments`, `segment_members`,
  `decision_state`, `schema_version`.
- **Unify identity:** drop `identity_map`; represent `(platform, source_id) -> entity`
  as `external_refs(source=platform, ref_value=source_id)`. Keep unresolved
  identities via an `unresolved` table or `decision_state(status='needs_identity')`.
- **Add `audit_log`** to the store (port reconcile-core's).
- **Handles first-class:** `contact_points(kind='handle', service=<platform>)`;
  `Reconciler` must union/dedup handles (currently ignored).
- **`StandardContact` bridge:** emails -> `email`, phones -> `phone`,
  urls -> `url` (service derived from hostname), handles -> `handle`
  (service=platform), imClients -> `handle`/dedicated `im` kind,
  `source_id` -> `external_ref`.

## 5. CLI surface (unified subcommands)

```
reconcile-core ingest <file> -p linkedin|discord|matrix|generic|google-csv
reconcile-core resolve            # interactive identity resolution (rich)
reconcile-core reconcile          # diff store vs a destination export / gws
reconcile-core export google-contacts | drumline-members
reconcile-core audit              # invariants + state report
reconcile-core migrate            # schema migrations
```

## 6. Data migration (the critical asset)

1. Copy the illini `contacts.db` into the new store path (default
   `$XDG_DATA_HOME/reconcile-core/contacts.db`, configurable `--db`).
2. Run a one-time loader that maps `identity_map` rows (if any) into
   `external_refs`; the curated overlays (alumni markers, 3 name resolutions,
   Rachel merge, verification, group status) are **already in the store** and
   come across unchanged.
3. **Acceptance:** post-migration counts match — 1,506 entities, 1,505
   `Contacts.csv` rows, 389 segment, 243 `external_status`, decision_state 6;
   parity test passes.

## 7. Drumline as a profile, not the project

- Move the drumline-specific imports/exports and the `illini-drumline-alumni`
  segment definition behind a `profile/drumline` module.
- The Google Groups provisioning tooling stays a separate, explicitly-invoked
  capability.
- After parity, **archive the illini repo** (or mark it read-only/reference).

## 8. Phases

| Phase | Work | Acceptance |
|---|---|---|
| **B0** | Pull the 1 remote commit; `uv sync`; run the 47-test baseline; snapshot | suite green |
| **B1** | Adopt store schema; port `contacts_store`/`labels`/`apply_hygiene`; `identity_map` -> `external_refs`; add `audit_log` | store tests pass |
| **B2** | Port `import_contacts`/`export_google_contacts` + parity test | content parity |
| **B3** | `StandardContact` -> store writer + identity resolution; rewrite `Reconciler` over store records **including handles**; replace `SQLitePersistence` | adapter + handle tests pass |
| **B4** | Migrate the illini DB; verify counts/parity | counts match |
| **B5** | Drumline profile (Tracker, decisions, members export); point group tooling | drumline tests pass |
| **B6** | Unify CLI; rewrite README/SETUP; regenerate `AGENTS.md` via `apm compile`; retire/archive illini | docs consistent |
| **B7** | Resume Google Groups adds on the new pipeline | 181 remaining progress |

## 9. Repo / PII / ops

- Illini data is PII; `reconcile-core` is on GitHub. **The store and DB files stay
  git-ignored**; `test_data/` stays no-PII (existing convention). Do not port
  illini's PII-bearing docs — they stay local.
- Docs changes go through `.apm/instructions/` + `apm compile`.
- Signed commits on `main`; confirm before pushing.

## 10. Risks & decisions to settle

1. **`gws` direction:** keep as an optional store->Google writer, or drop it and
   use the CSV import path only? (Recommend keep, but store-authoritative.)
2. **Store location:** XDG default vs repo-local `working/`? (Recommend XDG
   default + `--db` override.)
3. **Dependencies:** core stays stdlib-only; `rich` only in the CLI layer?
4. **Name:** keep `reconcile-core`, or rename (e.g. `contacts-core`)?
5. **Drumline location:** in-repo profile vs consuming the store from its own repo.
6. **Illini disposition:** archive after parity, or leave active as a domain consumer?

## 11. Effort

Roughly **5-6 focused days** (B0-B6), dominated by B3 (bridge + reconciler over
the store) and B5 (drumline profile). B7 is gated only by the Google cooldown.
This is a migration and unification, not a rewrite — the data and half the code
carry over.
