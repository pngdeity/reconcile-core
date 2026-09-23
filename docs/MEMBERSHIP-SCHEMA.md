# Membership Schema (drumline profile)

Membership is data, not prose. Until 2026-09-23 a person's seasons and sections
lived in `entities.notes` as an `IDL roster: Cymbals; 1991-1994` string; each
claim is now a row with cell-exact provenance, so it can be queried, exported,
verified, and corrected.

Profile migrations: `src/reconcile_core/profile/drumline/migrations/`
(`0004_affiliations.sql`, `0005_alias_provenance.sql`; `0006` adds
`affiliations.slot_label`). They land in the one shared store; numbering is
shared with the core migrations and applied by
`python -m reconcile_core.profile.drumline migrate`.

## Status (2026-09-23)

`0004`/`0005` are applied to the live store. The beatrack grid is versioned at
`source/idl-roster-beatrack.csv` (sha256
`bbe3e0a43cd777d4da6913bbdaa736ac835e78ce21b8682aead92605c04462e8`, registered as
source id 1, kind `roster-sheet`) and its backfill is complete: **1,426
affiliations over 556 people**, seasons 1911–2023, every row carrying cell-exact
provenance. The 346 `IDL roster: …` prose notes are retired (**0** remaining,
`audit_log` `RETIRE_ROSTER_PROSE`). From the same pass: 10 name claims
(nicknames, maiden names, one uncertain), 17 rows in the annotation review queue
(`decision_state` channel `idl-roster-annotation`) and 157 unresolved cells
(`unresolved_identities` platform `idl-roster-cell`). Still open: the
`export_members` columns (backfill step 8) and the second source below.

## The source grid

`source/idl-roster-beatrack.csv` is the beatrack historical roster: **71 rows x
116 columns**. Row 0 is the year header, one column per season, descending
(c0 = 2023 … c112 ≈ 1911). A **row is a slot inside a band**, a **column is a
season**, and a **cell is whoever held that slot that season**. Band blocks are
staggered (older eras have fewer slots above them), so the parser is a
per-column band walker and a `(season, section)` pair is a *derived* fact — the
provenance is always the cell, recorded as `source_ref = rNN:cNN`.

Consequences that shape the schema:

- Never store a derived `(year, section)` without the source location it came from.
- The slot row is captured as `slot` but **deliberately not interpreted** — if
  it turns out to mean "snare #1 vs #4", the data is already there. Slots are not
  always numeric: the audition bass line numbers its slots `0`–`5` *and* names one
  `Kicker`, so a named position needs `slot_label` rather than being forced into
  `slot`.
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
root: one row per beatrack sheet, audition document, inbox dump or group export.
Every affiliation and name claim points at a source and a location inside it.

`affiliations(id, entity_id, ensemble_key, role_key, season_year, season_label,
section_key, unit, slot, slot_label, source_id, source_ref, raw_text, confidence,
review_status, note, created_at, updated_at)`

- `season_year` is the academic year the season **starts** (fall); `season_label`
  is the header verbatim.
- `source_ref` **locates the claim inside its source** (paired with `source_id`):
  `rNN:cNN` for grid facts, `pN:lN` (page:line) for document facts. `raw_text`
  keeps the source text as written, before normalization.
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

## Second source: the audition documents (2025 and 2026)

Membership does not come only from the grid. Two PDFs are in play — one for the
2025 season, one for the 2026 auditions (they live in `~/downloads` today and must
be versioned under `source/` before their claims are loaded, or the provenance is
sand again):

**Season dating rule (confirmed 2026-09-23).** A season labelled `YYYY` begins in
August `YYYY` and runs through the following winter, and its auditions happen the
April shortly before that opening — in the same calendar year, not the previous
one. The audition's calendar year therefore **is** the `season_year`, with no
offset. The beatrack grid dates seasons the same way (its newest column header is
`2023`, and the parser reads the leading four digits verbatim), so the two sources
date seasons identically.

- `Marching Illini.pdf` — **FINAL RESULTS**, the authoritative confirmed-membership
  document. It names the season in prose (**2025**) and lists 38 people: Snares 12,
  Tenors 6, Bass 7, Cymbals 12, Undergraduate Staff 1. `Pierson Case` repeats
  across a page break (a rendering artifact, one person).
- `Marching Illini-2.pdf` — the final-round **in-person audition** invitation. A
  candidate list, **not** a membership list: "the live in-person audition is
  required for full consideration of being selected".

Two consequences already reflected above: geometry is not always a grid (hence
`pN:lN`), and slots are not always numeric (hence `slot_label`). `Kicker` is
**not a separate instrument**: it is the seventh bass drum, a position inside
`basses` (user ruling 2026-09-23), so it is captured as a named slot within that
section and never as its own section or role.

**TODO (accepted as inaccurate, 2026-09-23).** Two slot conventions coexist: the
beatrack grid's `slot` is a band-relative *ordinal* (1, 2, 3 …) while the audition
documents number bass positions from `0` and name the seventh drum `Kicker`. Each
source is stored verbatim, which is faithful but not one scheme; a later pass
should reconcile them (for example an ordinal column plus a source-order column)
whenever something actually needs to compare slots across sources. Deliberately
not urgent.

**Source strength (user ruling 2026-09-23).** The official Instagram feed
(`@illinidrumline`) counts as **sufficient membership evidence**, at the user's
discretion — it is the organisation's own account, not an anonymous feed. The
birthday posts themselves are irrelevant (a birthday is not a contact fact); the
value is the **name + nickname pairs** of current members. Those are inventory
claims (`alias_type='nickname'`); only a nickname someone genuinely goes by
reaches the `entities.nickname` scalar.

**Correction (2026-09-23).** The earlier `audition-2025` intake was built from
**both** documents, so **16 of its 24 "new members" were final-round candidates
only** — never selected. They were removed from the alumni segment (the Michael
Johnson precedent: no corroborated membership), their contact records kept and
`decision_state` rows written (`channel='audition'`, `status='rejected'`,
`source='audition-candidate-review'`), and their outreach claims corrected from
`Verified` / "Confirmed via audition results" to `Unknown` / unconfirmed. The 8
who do appear in the final results keep their confirmed status. The same intake
**missed 16 confirmed members** (Evanoff, Zhang, Campbell, Mathew, Bertrand,
Jerger, Harshbarger, Vanderkarr, H. Lester, Z. Evans, Anderson, L. Brown, Coyle,
McClendon, E. Nelson, Boone), and exactly one final-results person has no entity
at all (**Zane Evans**). Alumni segment: 713 → **697** after the removal, then
**698** once the 2025 results ingest created Zane Evans (entity 1915).

**Cycle of the audition PDF (resolved 2026-09-23).** It reads `SUNDAY APRIL 26`;
2025-04-26 was a Saturday and **2026-04-26 is a Sunday**, so by the dating rule
above it is the **2026** audition cycle, not the 2025 one. That is also why 2025
members reappear on it as candidates (Hawkins, Zhang, Pagan, Perlstadt, Sweitzer,
Case, Bailey, Mathew, Bartling, Campbell) — nobody is a candidate again in a cycle
whose results already listed them. The 16 people removed above were therefore
never 2025 members and are not 2025 rejects: they are unfilled candidates for the
2026 line.

Still open: whether a **2024** results document exists (it would fill the
2023→2025 gap) and whether a **2026** results document exists (it would confirm or
finally exclude those candidates, and would be the first affiliation newer than
2023).

## Backfill order

1. Version the raw sources (the beatrack sheet is now versioned; the inbox dumps
   and the audition PDFs are not).
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

Steps 1–7 are done for the beatrack source (1,426 affiliations + 4 duplicate
cells + 150 unresolved + 7 placeholders = the 1,587 historical person-year
count; retry is idempotent; 0 rejected entities hold affiliations). Step 8 is
done (`export_members` now emits `Season_First`, `Season_Last`, `Seasons_Count`,
`Sections`, `Role`, `Nickname`; 24 columns). The audition backfill is done too —
38 affiliations at `season_year=2025` from source 8, Zane Evans created — via
`audition-affiliations`, which reuses this module's name resolution rather than
the grid walker. Still outstanding: the inbox dumps are not versioned, the 157
unresolved grid cells and 17 annotation-review rows await review, and
`export public-roster` is not written.

## Open item

`tracker_verification` and `tracker_notes` each exist twice: as an alias (389
and 80 rows) and as a column on `drumline_outreach`. Collapsing them is the same
class of fix as this schema, and is not yet decided.
