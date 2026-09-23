# CONSOLIDATION-PLAN.md — Option B: `reconcile-core` as the umbrella

**Status:** active — B0–B6 + audition/needs-live-email done; the illini Google Groups campaign (B7) executed 2026-09-23 (0 remaining). Direction and boundaries settled (ADR-0001–0004). See §13.
**Created:** 2026-09-21
**Origin:** Illini Drumline contacts project (`~/repos/pngdeity/active/illini-drumline-contacts-alumni`)
decentered from its deadline; its normalized SQLite store is proposed as the
master data layer for `reconcile-core`.

## 1. Baseline facts (pre-consolidation, kept for history)

- `reconcile-core` is Python **3.14** (installed: 3.14.7), deps = `rich` only, MIT.
- `gws` CLI present at `/usr/bin/gws`.
- `AGENTS.md` is **APM-generated** from `.apm/instructions/` — edit the sources and run `apm compile`, never hand-edit.
- Local branch is in sync with `origin/main`.
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
| **B7** | Resume Google Groups adds on the new pipeline | 181 remaining progress; **out of scope per ADR-0001** (executed illini-side 2026-09-23: 421 entries, 0 remaining) |

## 9. Repo / PII / ops

- Illini data is PII; `reconcile-core` is on GitHub. **The store and DB files stay
  git-ignored**; `test_data/` stays no-PII (existing convention). Do not port
  illini's PII-bearing docs — they stay local.
- Docs changes go through `.apm/instructions/` + `apm compile`.
- Signed commits on `main`; confirm before pushing.

## 10. Risks & decisions to settle

All settled 2026-09-21 in `docs/adr/` (ADR-0001–0003). Original options kept for
history.

1. **`gws` direction:** keep as an optional store->Google writer, or drop it and
   use the CSV import path only? **Decided (ADR-0003):** keep as an optional
   writer; the store is authoritative.
2. **Store location:** XDG default vs repo-local `working/`? **Decided
   (ADR-0002):** XDG default + `--db`/`RECONCILE_CORE_DB` override; repo-local
   `var/` only for the drumline reference profile.
3. **Dependencies:** core stays stdlib-only; `rich` only in the CLI layer?
   **Decided (ADR-0002):** yes.
4. **Name:** keep `reconcile-core`, or rename (e.g. `contacts-core`)?
   **Decided (ADR-0002):** keep.
5. **Drumline location:** in-repo profile vs consuming the store from its own
   repo. **Decided (ADR-0001/0002):** in-repo reference consumer.
6. **Illini disposition:** archive after parity, or leave active as a domain
   consumer? **Decided (2026-09-21):** leave active; not archived.

## 11. Effort

Roughly **5-6 focused days** (B0-B6), dominated by B3 (bridge + reconciler over
the store) and B5 (drumline profile). B7 was gated only by the Google cooldown;
it is now out of scope (ADR-0001).
This is a migration and unification, not a rewrite — the data and half the code
carry over.

## 12. Baseline (B0)

Recorded 2026-09-21 at commit `9e0ed4a` (branch `main`, ahead of `origin/main` by 2).

- Python 3.14.7; uv 0.12.17
- `uv run pytest -q` -> **47 passed**
- Working tree clean; `git pull --ff-only` reported up-to-date (`origin/main` = `c770245`, fully merged)

This is the green baseline that every later phase must preserve.

## 13. Phase log

- **B0 DONE (2026-09-21):** pulled to `c770245`; baseline suite green (47 passed); recorded above.
- **B1 DONE (2026-09-21):** ported the store into `src/reconcile_core/store/` (migration `0001_init.sql`, `migrate.py` runner, `store.py` helpers, `labels.py`); unified identity by replacing `identity_map` with `external_refs` (platform identity -> entity, Google resourceName as the `google` ref); kept `audit_log` and `unresolved_identities`; `database.py` is now store-backed. Test suite **61 passing** (47 baseline + 14 new: `tests/test_store.py` + cross-platform convergence in `tests/test_persistence.py`).
- **B2 DONE (2026-09-21):** ported the Google Contacts CSV projection into `src/reconcile_core/io/google_csv.py` (`import_contacts`, `export_contacts`, 62/61-column headers, marker->segment bridge); `tests/test_io_google_csv.py` round-trips a synthetic no-PII CSV cell-for-cell. Suite **67 passing**. Validated on the real illini `Contacts.csv` (1,505 rows) with zero cell differences.
- **B3 DONE (2026-09-21):** added `src/reconcile_core/store/bridge.py` (`write_contact` resolves `(platform, source_id)` -> email -> new entity and unions emails/phones/urls/handles/imClients with zero loss; `contact_from_entity` reconstructs a `StandardContact` from store points); `SQLitePersistence` gained `ingest`, `contact_from_entity`, `contact_for_identity`, `find_entity_by_email`; the `Reconciler` now unions **handles** by `(platform, username)`. `tests/test_bridge.py` (6) + handle tests in `tests/test_reconciliation.py`. Suite **75 passing**.
- **B5 DONE (2026-09-21):** added `src/reconcile_core/profile/drumline/` (migration `0002_drumline_outreach.sql`; `import_drumline` for Tracker links/segment/decision state; `name_resolutions`; `import_master` outreach seed; `export_members` person CSV; `config.py` reading PII configs from git-ignored `var/drumline/`); `store/migrate.py` `discover`/`apply_migrations`/`status` now accept `extra_dirs` so profiles own their migrations; single CLI `python -m reconcile_core.profile.drumline <command>`. Fixed a latent illini bug (address-map entries now resolve by `tracker_id` ref). `tests/test_drumline_profile.py` (5). Acceptance against the real imported store: Segment 389, decision_state 6, `export_members` produced **389 rows / 18 cols with id sets equal and 0 cell differences** vs illini `drumline-members.csv` (after the correct order: import-master before name-resolutions). Suite **84 passing**.
- **B4 DONE (2026-09-21):** store was **repo-local** at this phase (`var/contacts.db`, git-ignored; `RECONCILE_CORE_DB` override); decision #2 was later settled as an XDG default with repo-local retained for the drumline profile (ADR-0002). Added `src/reconcile_core/store/import_db.py` (+ CLI) to import the legacy illini DB and **re-stamp `schema_version`** to this package's consolidated baseline (legacy 1-4 would otherwise shadow future migrations); unowned tables (e.g. `drumline_outreach`) survive and become pending migrations when their migration is added in B5. Imported the real illini store and verified acceptance: **1,506 entities, 389-person segment, 243 external_status, 6 decision_state**, and CSV export parity against illini `Contacts.csv` (**1,505 rows, id sets equal, 0 cell differences**). `tests/test_import_db.py` (4). Suite **79 passing**.
- **Audition-2025 integration (2026-09-21):** new profile importer `profile/drumline/audition_members.py` (+ CLI command `audition-members`) applies `var/drumline/audition_members.json`: 14 name-fills on nameless member entities and 24 new member entities (anchored by an `audition-2025` external ref, added to the alumni segment, seeded `Verified` with `review_status='Confirmed via audition results'`). Segment 389 → **413** (98 nameless remain); `tests/test_audition_members.py` (4). Idempotent; name-fills only touch empty fields and report conflicts. Regenerated `drumline-members.csv` (413 data rows); `Contacts.csv` unchanged (new members have no Google refs). Suite **97 passing**.
- **B6 DONE (2026-09-21):** unified CLI `python -m reconcile_core` (`src/reconcile_core/cli.py` + `__main__.py`): `migrate` (optional `--profile drumline`, `--status`), `ingest`, `resolve`, `reconcile` (dry-run default; `--apply` performs the zero-loss union), `export google-contacts|drumline-members`, `audit`. `store/bridge.write_contact` gained an explicit `entity_id` so additions can be applied to a known entity. Legacy `main.py` Google-API path retained. Agent-context Quick Start, structure table, and README updated (test count 93; handles-reconciled limitation removed). `tests/test_cli.py` (9). Suite **93 passing**. **The illini project is NOT archived — user decision (2026-09-21).**
- **B7-prep DONE (2026-09-21):** added `profile/drumline/needs_live_email.py` + the `needs-live-email` CLI command, deriving the research backlog from the store (rule: a segment member needs a live email when they have no email contact point, or every email is non-live — `bouncing`/`invited` — in `external_status`; reachability is per person). Replaces the hand-maintained illini CSV, which had drifted. Derived 63 rows for the current store. `tests/test_needs_live_email.py` (2). Suite **99 passing**.
- **C0 DONE (2026-09-21):** direction and boundaries settled in `docs/adr/` (ADR-0001–0004): emphasis on the general engine (P1); XDG store default with repo-local for the drumline profile; Google Contacts as one projection with the legacy `main.py` entry slated for retirement; and the P1 delivery roadmap. B7 (Google Groups) is out of scope; the drumline profile is a reference consumer.
- **C2 DONE (2026-09-21):** identity resolution over the store. Added `src/reconcile_core/store/identity.py`: `find_duplicates` (deterministic shared-contact-point + name-token scoring; conservative default threshold, name-only pairs hidden), `merge_entities` (lossless move of refs/points/addresses/aliases/segment membership/decision state/external status; preserves a differing source name as an alias; dedupes only exact normalized points carrying no address or decision state), `split_entity` (moves selected refs/points to a new entity; raises on stray ids). New CLI: `duplicates`, `merge SOURCE TARGET [--reason]`, `split ENTITY [--ref SOURCE:VALUE] [--point ID] [--name]`. Legacy `main.py` retired (ADR-0003): `ADAPTER_CLASSES` moved to `adapters/__init__.py`; the fuzzy matcher became `name_similarity` in `identity.py`. `tests/test_identity.py` (15). Suite **127 passing**.
- **C1 DONE (2026-09-21):** added `store/backup.py` (`snapshot` via `VACUUM INTO`, atomic `restore`, `verify` with integrity/schema/counts) exposed as `reconcile_core backup|restore`; the live store was snapshotted to `var/backups/contacts-20260921-205511.db`. Also silenced the pre-existing runpy warning for `python -m reconcile_core.store.*` via lazy package exports. `tests/test_backup.py` (9) + module-CLI warning test. Suite **112 passing**.
- **C4 DONE (2026-09-21):** added the synthetic no-PII corpus `test_data/corpus/` (LinkedIn/Discord/Matrix/generic exports plus a sparse Google Contacts spec) and `tests/test_corpus.py` (8): golden store projection `store_golden.json`, cross-platform convergence via a shared (case-insensitive) email, handle-only platforms staying separate, idempotency, blocked-relationship exclusion, display-name collision surfaced but not applied, and cell-for-cell Google projection round-trip.
- **D6 DONE (2026-09-21):** CI at `.github/workflows/ci.yml` (`uv sync --frozen`, `ruff check src tests`, `pytest -q`) with a README badge; `ruff` added to the dev group with an explicit `[tool.ruff.lint] select` so upgrades cannot silently change what passes. Suite **120 passing**.
- **IDL roster integration DONE (2026-09-22):** added `profile/drumline/idl_roster.py` + the `idl-roster` CLI command, applying `var/drumline/idl_roster.json` (built from the published beatrack IDL historical roster, 71 seasons 2023→1911). Applied to the live store: 9 segment additions, **371 new alumni** entities (anchored by `idl-roster` external refs, verification `Roster-derived`, `review_status='Confirmed via IDL roster'`), **11 staff-only** entities in the new `idl-staff` segment, and 5 name aliases; idempotent. Alumni segment 413 → **793**; entities 1,530 → **1,912**. Regenerated `deliverables/drumline-members.csv` (793 rows) and the derived needs-live-email backlog (63 → **435**); `Contacts.csv` unchanged (new members have no Google refs). `tests/test_idl_roster.py` (2); suite **129 passing**; illini `audit_integrity.py` 13/13.
- **IDL roster duplicate folds DONE (2026-09-22):** 15 probable-duplicate pair-rows / 16 folds resolved with the existing `merge SOURCE TARGET --reason` CLI (`merge_entities`). Kept-sides: Russell Duszak, Jeffrey Trimble, David Patterson (2 folds), Dave Theis, Levi McCullough, Ian Shepard, Rose Esseks, John Eifert, Paul Kendeigh, Jason Valluzi, Tobi Steinberg, Jeff Hoffee, Dario Civinelli, Rick Waller, Kevin Eckland. `Rich Carlson` (Snare 2002) / `Richard Carlson` (Timpani 1978) intentionally left separate (different eras and sections). Paul Kendeigh's 1988 `idl-staff` row moved onto his alumni entity, so he holds both memberships. Entities 1,912 → **1,896**; alumni 793 → **778**; `idl-staff` 11; `external_refs` unchanged at 2,689 (refs re-pointed, not dropped); 16 `name` aliases + 16 `audit_log` MERGE rows. Projections regenerated (`drumline-members.csv` 778 rows; needs-live-email 435 → **420**); `Contacts.csv` still unchanged.
- **Core store schema anomaly found + repaired (2026-09-22):** the live `var/contacts.db` recorded `schema_version` `init`/`drumline_outreach` but was missing `audit_log` and `unresolved_identities` (the bootstrap path applied the version rows without the full `0001_init.sql`); a fresh `apply_migrations` DB has both. Repaired additively with `CREATE TABLE IF NOT EXISTS` (DDL from `0001_init.sql` lines 74-81) after backing up to `var/backups/contacts_pre_merge_idl_dupes_20260922.db`. Recommended follow-up: a versioned core repair migration so other stores from the same path self-heal.
- **Merge position-collision fix + nameless-member folds (2026-09-22):** folded 19 nameless alumni onto their roster names by email local part (`first-initial + surname`) plus 9 roster-internal duplicate pairs the 0.88 similarity report missed (`Michael/Mike Boykins`, `Brody`, `Croix`, `Rose/Rosemary Esseks`, `Jennifer/Jenny Hansen`, `Thomas/Tom Kelly`, `Rob/Robert Madsen`, `Andrew/Andy Stein`, `Stephen/Steve Theis`) = **28 folds**, all preserving the folded spelling as a `name` alias. The folds exposed a latent bug: `merge_entities` moved contact points without renumbering, so two points could share a `position`, and the Google exporter (position-keyed `E-mail 1/2/3` slots) silently dropped one — losing addresses from the projection. Added `_renumber_positions` (per kind; the target's own points keep the low slots) + `tests/test_identity.py::test_merge_renumbers_colliding_positions`; 7 live rows renumbered; now 0 duplicate slots and 0 NULL positions store-wide. Also dropped two redundant `google_contacts_id` refs (485/922) so Erik Olson and Kevin Lyvers each project as one row (Tracker 5020/5044 re-pointed to 910/499). Store: entities 1,912 → **1,868**; alumni 793 → **750**; nameless alumni 98 → **79**; `name` aliases 16 → **25**. Projections: `Contacts.csv`/`Contacts_import.csv` **1,503 rows**; `drumline-members.csv` **750 rows**; needs-live-email 420 → **394**. Suite **132 passing**; illini `audit_integrity.py` 13/13.
- **B7 DONE (2026-09-23, illini-side):** the Google Groups add/invite campaign completed against the rebuilt target — 24/24 direct-add + 157/157 invite submitted (runner state 277 `processed` / 0 failed / 0 pending), the live group export grew 243 → **421 entries** (252 `member` + 168 `invited` + 1 `owner`), and the run lists were rebuilt to **0 remaining** (425-address target, 420 in group). 3 addresses were silently refused by Google (`dvadams@aol.com`, `jjaruseski@naperville203.org`, `joej@naperville203.org`), 1 invite was accepted under a different address (`gmkwain@aol.com` → `gmkwain1@gmail.com`, added to entity 1501 on 2026-09-23), and 1 is blocked (`obrgr20@sages.us`); all remain in the store/target (Contact-Completeness) and are recorded in the illini `working/group_blocked.json`. Gotcha documented: `working/build_group_lists.py` reads the **legacy** illini store plus the `external_status` snapshot, so `working/import_group_status.py` must run after every export or the lists rebuild stale. No CAPTCHA wall or daily-limit stop occurred.
- **Google Groups tooling ported to the core store (2026-09-23):** added `profile/drumline/import_group_status.py` (`import-group-status`: Google Groups export → dated `external_status` snapshot, idempotent per day via `ux_external_status`) and `profile/drumline/group_lists.py` (`group-lists`: target + MX-aware run lists, explicit `--target-dir`/`--run-dir` so no PII lands in this repo). Both are faithful ports of the illini `working/` scripts, which are now **deprecated aliases** delegating here (same pattern as `export_drumline_members.py`; core checkout via `$RECONCILE_CORE_DIR`). The core DB held only the stale Sep 21 snapshot (244 rows), so the port's first action was ingesting the Sep 23 export (421 rows, 421 linked). Parity: the ported builder targets **435** addresses vs the legacy 425 — the extra 10 belong to the 9 people the IDL-roster import added to the alumni segment plus `gmkwain1@gmail.com` (already in group), i.e. strictly more complete; **0 addresses were lost**. Remaining after the port: 14 (13 non-.edu + 1 .edu), run lists 3 direct-add + 10 invite, skip 421, 1 blocked. `tests/test_group_lists.py` (5) + `tests/test_import_group_status.py` (4); suite **141 passing**; `ruff` clean.
- **IDL-roster false positives found, gated, and fixed (2026-09-23):** a user report (`michael.johnson@physoft.com` is not an alumnus) exposed the `entity` class in `working/match_idl_roster.py` — an EXACT full-name match to a store contact outside the alumni segment was auto-appended to `segment_additions` by `working/build_idl_roster_config.py` with **no human gate**, while the WEAKER `review` band (0.60-0.80) did require explicit decisions. Nine such additions had been applied; the evidence table showed 937 Michael Johnson as a confirmed false positive (no tracker ref, no dump presence, no store note) and 318 David Schroeder / 890 Mark Edwards / 1308 Thomas Eifert as uncorroborated. Remediation: 937 removed from the group (user) and rolled back in the store; 318/890/1308/937 removed from the segment and recorded as `decision_state` (`channel='idl-roster'`, `status='rejected'`, `source='manual_review'`); 419/947/1011/1328/1444 kept (tracker ref, email-name agreement, store note, or user memory). Pipeline fix: `idl_roster.apply_idl_roster` now skips entities carrying a `rejected` marker and reports `segment_additions_skipped`, and the config generator only emits explicitly approved entity matches (`APPROVED_SEGMENT_ADDITIONS`) — anything else is flagged. Two secondary audits followed: **7 spelling/annotation duplicates folded** (Curt Scwarzkopf→Curt Schwarzkopf, Matt McKracken→Matt McCracken, Celeste Tomasell→Celeste Tomaselli, Nayan Bahi→Nayan Bahl, Brian O'Connor-B line→Brian O'Connor, Geoff Swanson B-line→Geoffrey Swanson, Graham Stapleton B-Line→Graham Stapleton) plus **5 married-name/nickname variants** (Debbie Kashmier Boehm, Jennifer Ray Coval, Steve Theis (Zoidberg), Greg Bilecki, Peggy Snyder) — every folded name kept as a `name` alias, notes carried over, nothing deleted; and `working/parse_idl_roster.py` now strips space-separated `B-line`/`-B line` suffixes and the `, maybe <surname>` annotation. Store after: alumni **734**; `drumline-members.csv` 734; target 431 (421 in group), remaining 10 (1 direct-add + 8 invite + 1 blocked); needs-live-email **480**; `audit_integrity.py` 13/13; suite **142 passing**. Backups: `var/backups/contacts_pre_falsepositive_rollback_20260923.db`, `contacts_pre_segment_filter_20260923.db`, `contacts_pre_dupfix_20260923.db`, `contacts_pre_dupfix2_20260923.db`.
- **Nameless-address naming pass + Waller/Walter correction (2026-09-23):** the 70 non-`.edu` nameless alumni addresses were run through an evidence-tiered candidate builder (illini `working/build_nameless_candidates.py`; tiers = inbox-dump display names, Google Groups nicknames that are real names, and a tightened person-only local-part inversion). Applied **16 lossless folds** (the address belongs to an existing person who had no email: Kevin Gier, Graham Stapleton, Pete Kikta, Todd Miller, Shrenik Balaji, Andy Stein, Jim Nevermann, Joe Freda, Jon Adams, Mike Dankler, Trent Shuey, Ron Lambert, Tom Kundmann, Justin Schwarzentraub, Bill Ronna, Rick Walter) and **8 names** through the versioned `var/drumline/manual_name_resolutions.json` (now 11 resolutions, incl. `majohn71@gmail.com` -> Michael Johnson, deliberately NOT folded into the un-alumnused entity 937). 45 addresses had no candidate. Naming-pass artifact: entity 1328 held two `google_contacts_id` refs, so the redundant nameless id 1580 was dropped (keeping 940, Tracker 5382's reference). Nameless alumni 79 -> **55**; alumni 726 -> **712**. The user then corrected an earlier mistaken instruction: `Rick Waller` (Cymbals 1991-1994) and `Rick Walter` (Snare 1993-1996) are two different people, so entity **1914 'Rick Walter'** was restored with the `walter.rick@gmail.com` identity (`google_contacts_id=1647`, `tracker_id=5333`, `master_person_id=P0291`, `idl-roster=rick-walter`) and 1845 kept only `idl-roster=rick-waller`. Final: `Contacts.csv`/`Contacts_import.csv` **1,502**, `drumline-members.csv` **713**, target 431 (426 in group, 5 blocked), `needs-live-email` **462**, illini `audit_integrity.py` 13/13, reconcile-core 142 tests.
