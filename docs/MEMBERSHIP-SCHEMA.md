# Membership Schema (drumline profile)

Membership is data, not prose. Today a person's seasons and sections live in
`entities.notes` as an `IDL roster: Cymbals; 1991-1994` string; this schema
makes each claim a row with cell-exact provenance, so it can be queried,
exported, verified, and corrected.

Profile migrations: `src/reconcile_core/profile/drumline/migrations/`
(`0004_affiliations.sql`, `0005_alias_provenance.sql`). They land in the one
shared store; numbering is shared with the core migrations and applied by
`python -m reconcile_core.profile.drumline migrate`.

## The source grid

`source/idl-roster-beatrack.csv` is the beatrack historical roster: **71 rows x
116 columns**. Row 0 is the year header, one column per season, descending
(c0 = 2023 … c112 ≈ 1911). A **row is a slot inside a band**, a **column is a
season**, and a **cell is whoever held that slot that season**. Band blocks are
staggered (older eras have fewer slots above them), so the parser is a
per-column band walker and a `(season, section)` pair is a *derived* fact — the
provenance is always the cell, recorded as `source_ref = rNN:cNN`.

Consequences that shape the schema:

- Never store a derived `(year, section)` without the cell it came from.
- The slot row is captured as `slot` but **deliberately not interpreted** — if
  it turns out to mean "snare #1 vs #4", the data is already there.
- A cell can hold an annotation as well as a name (`Steve Theis (Zoidberg)`),
  and the parenthesis has five different meanings. Annotations are claims, and
  ambiguous ones go to a review queue, never to a silent guess.

## Vocabulary (locked)

| key | label | sort | source labels mapped |
|---|---|---|---|
| `snares` | Snares | 1 | `Snare:`, `Snare` |
| `tenors` | Tenors | 2 | `Tenors:` |
| `basses` | Basses | 3 | `Basses:` |
| `cymbals` | Cymbals | 4 | `Cymbals:` |
| `glockenspiels` | Marching Glockenspiels & Bell Lyres | 5 | `Keyboard:` |
| `timpani` | Timpani | 6 | `Timpani:` |

Roles: `member` (Member), `staff` (Staff). **Staff is a role, not a section** —
the sheet's `Staff:` band is a role label, and the same person can be both
(Paul Kendeigh, Jim Nevermann, Trent Shuey are members and staff).

Sections and roles are lookup tables (`sections`, `roles`), so the vocabulary is
enforced rather than conventional and the long display label never becomes a
foreign key.

## Tables

`sources(id, name UNIQUE, kind, url, fetched_at, sha256, note)` — the ingest
root: one row per beatrack sheet, inbox dump or group export. Every affiliation
and name claim points at a source and a location inside it.

`affiliations(id, entity_id, ensemble_key, role_key, season_year, season_label,
section_key, unit, slot, source_id, source_ref, raw_text, confidence,
review_status, note, created_at, updated_at)`

- `season_year` is the academic year the season **starts** (fall); `season_label`
  is the header verbatim.
- `source_ref` is `rNN:cNN` for grid facts (paired with `source_id`); `raw_text`
  keeps the cell as written, before normalization.
- `unit` holds a sub-unit marker such as `B-Line` once its meaning is confirmed.
- Uniqueness: `(entity_id, ensemble_key, role_key, season_year, section_key,
  source_id)`, expressed with a `coalesce(section_key, '')` key so section-less
  staff rows still collapse.
- `review_status`/`confidence` mirror the store-wide idiom; a claim that needs a
  human decision is recorded, not dropped.

`aliases` gains `confidence`, `observed_at`, `source_ref` (`0005`), turning each
name claim into a sourced claim. `alias_type` vocabulary: `name`, `nickname`,
`former_name`, `maiden_name`, `legal_name`, `roster_spelling`, `unit`, `aka`,
plus legacy carriers (`tracker_verification`, `tracker_notes`, `relation`,
`pronunciation`, `slot_label`).

## Nicknames: inventory vs "goes by"

Two different facts, two different places:

- **Inventory** — a nickname the roster records: `aliases(alias_type='nickname',
  alias_value='Zoidberg', source='idl-roster', source_ref='r18:c17')`. Multiple
  nicknames are ordered by `aliases.position`.
- **"Goes by"** — the name someone is actually known by (some people are
  synonymous with a nickname; their friends forget the real name):
  `entities.nickname`, the scalar that drives the Google Contacts Nickname.
  Precedent: `entities.nickname = 'Gabe'` for George David Dungan III.

`(Zoidberg)`, `(Nibbler)`, `(Franchez)`, `(Cluster)` → nickname claims.
`(Zaun)`, `(Friddle)`, `(Wafler)` in `Stacy (Zaun) Eifert` → `maiden_name`.
`(Bucky)?` → a nickname claim with `confidence='uncertain'`.
`(Max)` (Karen Max Parkinson) → review queue: maiden name or nickname is
undecided. `(bongo)`, `(timbali)` and `B-Line` → review queue, never
auto-assigned.

## Backfill order

1. Version the raw sources (the beatrack sheet and the inbox dumps are currently
   unversioned; an unversioned provenance root makes everything downstream sand).
2. Apply `0004`/`0005` — additive, no data change.
3. Parser v2 emits cell-keyed records (`source_ref=rNN:cNN`).
4. Match cells to entities via the existing `idl-roster` slug refs; unmatched
   cells land in `unresolved_identities`.
5. Load `affiliations`; load nickname/former-name claims; queue the ambiguous
   annotations.
6. **Verify the invariant**: every grid cell containing a name resolves to
   exactly one of — an affiliation, an annotation claim, or a review row.
   Nothing silently dropped.
7. Only then retire the 346 prose notes (backup + `audit_log` entry).
8. Extend `export_members` with structured columns (`Season_First`,
   `Season_Last`, `Seasons_Count`, `Sections`, `Role`, `Nickname`) in place of
   prose. `export public-roster` (allowlisted fields, no PII) comes after.

## Open item

`tracker_verification` and `tracker_notes` each exist twice: as an alias (389
and 80 rows) and as a column on `drumline_outreach`. Collapsing them is the same
class of fix as this schema, and is not yet decided.
