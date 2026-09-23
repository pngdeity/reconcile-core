# Drumline profile

Domain layer for the Illini Drumline, on top of the generic contacts store.

## What it does

- **Migrations** (`migrations/0002_drumline_outreach.sql`): adds the
  `drumline_outreach` per-person status overlay. Applied via
  `reconcile_core.profile.drumline.migrate` alongside the core migrations.
- **`import_drumline`**: links every `Tracker.csv` row to an entity
  (`tracker_id`), creates entities for Tracker-only persons, adds them to the
  `illini-drumline-alumni` segment, applies explicit entity merges, and imports
  decision state from the routing configs.
- **`name_resolutions`**: applies the versioned manual name resolutions
  (field overrides, aliases, verification sync).
- **`audition_members`**: applies the versioned audition-results config
  (`var/drumline/audition_members.json`): fills names on nameless member entities
  and creates entities for new members (anchored by an `audition-*` external ref,
  added to `illini-drumline-alumni`, seeded `Verified` in `drumline_outreach`).
- **`import_master`**: one-time seed of `master_person_id` refs, primary email,
  and the `drumline_outreach` overlay from the legacy master CSV.
- **`export_members`**: generates the person-level `drumline-members.csv`.
- **`needs_live_email`**: derives the needs-live-email research backlog (members with no email or only non-live addresses) from the store.
- **`idl_roster`**: ingests the published beatrack IDL historical roster — segment additions, new alumni (anchored by `idl-roster` refs), and staff-only entities in a separate `idl-staff` segment.
- **`import_group_status`**: snapshots a Google Groups membership export into `external_status` (dated, idempotent per day).
- **`group_lists`**: builds the Google Groups target + MX-aware run lists (`group_target.csv`, `google_remaining.txt` / `other_remaining.txt` / `skip_members.txt`) from the store. Paths are explicit (`--target-dir`, `--run-dir`) so no PII is written under this repo.

## PII

`Tracker.csv`, the legacy master CSV, and all `manual_*` JSON configs contain
real names and addresses, so they are **not** in this repository. The configs
are read from the repo-local, git-ignored `var/drumline/` (override with
`--config-dir` or `RECONCILE_CORE_DRUMLINE_CONFIG`); data paths are passed with
`--tracker` / `--input` / `--out`.

## Usage

Refresh order matters: run `audition-members` after `import-drumline` (so the
segment exists), run `idl-roster` after `audition-members`, and `import-master`
**before** `name-resolutions` (the seed overwrites the outreach overlay).

```bash
# core + drumline migrations
uv run python -m reconcile_core.profile.drumline migrate --db var/contacts.db

# membership + decision state
uv run python -m reconcile_core.profile.drumline import-drumline \
    --tracker /path/Tracker.csv --db var/contacts.db

# audition name-fills + new members (config: var/drumline/audition_members.json)
uv run python -m reconcile_core.profile.drumline audition-members --db var/contacts.db

# beatrack IDL historical roster (config: var/drumline/idl_roster.json)
uv run python -m reconcile_core.profile.drumline idl-roster --db var/contacts.db

# one-time outreach seed from the legacy master (before name-resolutions)
uv run python -m reconcile_core.profile.drumline import-master \
    --input /path/drumline-master-v2.csv --db var/contacts.db

# manual name resolutions
uv run python -m reconcile_core.profile.drumline name-resolutions --db var/contacts.db

# generate the member list
uv run python -m reconcile_core.profile.drumline export-members \
    --out var/drumline-members.csv --db var/contacts.db

# derive the needs-live-email backlog
uv run python -m reconcile_core.profile.drumline needs-live-email \
    --out var/group_needs_live_email.csv --db var/contacts.db

# Google Groups: snapshot the export, then rebuild the target + run lists
uv run python -m reconcile_core.profile.drumline import-group-status \
    --input /path/group-membership.csv --db var/contacts.db
uv run python -m reconcile_core.profile.drumline group-lists \
    --target-dir /path/working --run-dir /path/browser-approach --db var/contacts.db
```

`uv run pytest -q tests/test_drumline_profile.py tests/test_audition_members.py tests/test_idl_roster.py tests/test_group_lists.py tests/test_import_group_status.py`
covers all of the above with synthetic, no-PII fixtures.
