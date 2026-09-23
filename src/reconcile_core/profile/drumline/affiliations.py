"""Backfill structured affiliations from the beatrack roster grid.

The grid (``source/idl-roster-beatrack.csv``) is 71 rows x 116 columns: row 0 is
the season header, a row is a slot inside a band, a column is a season, and a
cell is whoever held that slot that season. This module turns each named cell
into an ``affiliations`` row whose provenance is the cell itself
(``source_ref = rNN:cNN``), and turns each annotation into a sourced name claim
or a review row. Nothing is dropped: a cell that cannot be resolved to a person
lands in ``unresolved_identities``.

Decisions this implements (see ``docs/MEMBERSHIP-SCHEMA.md``):

- Section and role vocabulary from the lookup tables; ``Staff`` is a role.
- ``season_year`` is taken from the header, ``season_label`` kept verbatim.
- ``slot`` is the band-relative ordinal, captured but not interpreted.
- ``(Zoidberg)`` style annotations become ``nickname`` claims; ``(Zaun)`` style
  become ``maiden_name``; ambiguous ones go to the review queue, never guessed.

Idempotent: re-running inserts nothing new.
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

from ...store import store
from .idl_roster import _slug
from .sources import register_source

SOURCE_NAME = "idl-roster-beatrack"
SOURCE_KIND = "roster-sheet"
SOURCE_URL = "https://beatrack.com/idl/roster.htm"
ROSTER_REF = "idl-roster"
ENSEMBLE_KEY = "illini-drumline"
ALUMNI_SEGMENT = "illini-drumline-alumni"
STAFF_SEGMENT = "idl-staff"
ANNOTATION_CHANNEL = "idl-roster-annotation"

# Source band label -> (role_key, section_key). The sheet writes the label with
# and without a trailing colon, and repeats it across the columns it covers.
BANDS: dict[str, tuple[str, str | None]] = {
    "snare:": ("member", "snares"),
    "snare": ("member", "snares"),
    "tenors:": ("member", "tenors"),
    "tenors": ("member", "tenors"),
    "basses:": ("member", "basses"),
    "basses": ("member", "basses"),
    "cymbals:": ("member", "cymbals"),
    "cymbals": ("member", "cymbals"),
    "keyboard:": ("member", "glockenspiels"),
    "keyboard": ("member", "glockenspiels"),
    "timpani:": ("member", "timpani"),
    "timpani": ("member", "timpani"),
    "staff:": ("staff", None),
    "staff": ("staff", None),
}

# Curated annotation decisions. Everything not listed here goes to the review
# queue: the parenthesis is not evidence enough to pick a semantic.
NICKNAMES = {"zoidberg", "nibbler", "franchez", "cluster", "bucky"}
MAIDEN_NAMES = {"zaun", "friddle", "wafler"}
UNIT_TOKENS = {"b-line", "b line", "bline", "cart"}
INSTRUMENTISH = {"timbali", "bongo"}

PAREN = re.compile(r"\(([^)]*)\)")
MAYBE = re.compile(r",\s*maybe\s+(.+)$", re.IGNORECASE)
TRAILING_UNIT = re.compile(r"\s*[-\u2013]?\s*\b(b[-\s]?line|cart)\b[\s.]*$", re.IGNORECASE)


def _clean_name(raw: str) -> str:
    """Normalize a cell to a person name (the parse used by the roster import)."""
    name = raw.strip().strip("*").strip().rstrip("?").strip()
    name = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", ". ", name)
    name = re.sub(r"\s*[-\u2013]\s*", "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    if name.count(",") == 1:
        last, first = (part.strip() for part in name.split(","))
        if last and first:
            name = f"{first} {last}"
    return name


def parse_cell(raw: str) -> dict:
    """Split one cell into a cleaned name plus the claims it carries.

    Returns ``{"name": str, "annotations": [{"kind", "value", "confidence"}]}``
    where ``kind`` is an ``aliases.alias_type`` or ``"review"``.
    """
    text = raw.strip()
    annotations: list[dict] = []

    hedge = MAYBE.search(text)
    if hedge:
        annotations.append(
            {
                "kind": "name",
                "value": hedge.group(1).strip(),
                "confidence": "uncertain",
                "note": "source hedge (', maybe ...')",
            }
        )
        text = text[: hedge.start()]

    uncertain = text.rstrip().endswith("?")
    if uncertain:
        text = text.rstrip().rstrip("?").strip()

    for match in PAREN.finditer(text):
        value = match.group(1).strip()
        after = text[match.end() :].strip()
        low = value.lower()
        kind = "review"
        if low.startswith("aka"):
            kind, value = "aka", value[3:].strip()
        elif low in UNIT_TOKENS:
            kind = "unit"
        elif low in INSTRUMENTISH:
            kind = "review"
        elif low in NICKNAMES:
            kind = "nickname"
        elif low in MAIDEN_NAMES:
            kind = "maiden_name"
        annotations.append(
            {
                "kind": kind,
                "value": value,
                "confidence": "uncertain" if uncertain else "likely",
                "note": "trailing" if not after else "mid-name",
            }
        )
    text = PAREN.sub(" ", text)

    unit = TRAILING_UNIT.search(text)
    if unit:
        annotations.append(
            {
                "kind": "unit",
                "value": unit.group(1),
                "confidence": "likely",
                "note": "unparenthesised suffix",
            }
        )
        text = text[: unit.start()]

    return {"name": _clean_name(text), "annotations": annotations}


def _season_year(label: str) -> int | None:
    match = re.match(r"(\d{4})", label.strip())
    return int(match.group(1)) if match else None


def _is_placeholder(name: str) -> bool:
    return not name or "_" in name or name.lower() in {"tbd", "unknown"}


def _normalize_name(value: str) -> str:
    """Fold case, apostrophes, dashes and punctuation for name comparison."""
    text = unicodedata.normalize("NFKD", value or "")
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace(".", "")
    text = re.sub(r"[^a-z0-9' -]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _name_index(conn) -> dict[str, list[int]]:
    """Normalized name -> entity ids, for people already in the roster segments.

    Covers display names, first+last, and the stored alternate name forms
    (``name`` / ``aka`` / ``roster_spelling`` / ``legal_name`` / ``maiden_name``)
    so a roster spelling the store already knows resolves without a guess.
    """
    index: dict[str, list[int]] = {}

    def add(key: str, entity_id: int) -> None:
        if key and entity_id not in rejected and entity_id not in index.setdefault(
            key, []
        ):
            index[key].append(entity_id)

    rejected = {
        row[0]
        for row in conn.execute(
            "SELECT entity_id FROM decision_state WHERE channel=?"
            " AND status='rejected'",
            (ROSTER_REF,),
        )
    }

    rows = conn.execute(
        "SELECT e.id, e.display_name, e.first_name, e.last_name FROM entities e"
        " JOIN segment_members m ON m.entity_id = e.id"
        " JOIN segments s ON s.id = m.segment_id"
        " WHERE s.name IN (?, ?)",
        (ALUMNI_SEGMENT, STAFF_SEGMENT),
    )
    for entity_id, display, first, last in rows:
        for value in (display, f"{first or ''} {last or ''}".strip()):
            add(_normalize_name(value), entity_id)

    aliases = conn.execute(
        "SELECT a.entity_id, a.alias_value FROM aliases a"
        " JOIN segment_members m ON m.entity_id = a.entity_id"
        " JOIN segments s ON s.id = m.segment_id"
        " WHERE s.name IN (?, ?) AND a.alias_type IN"
        " ('name','aka','roster_spelling','legal_name','maiden_name')",
        (ALUMNI_SEGMENT, STAFF_SEGMENT),
    )
    for entity_id, alias_value in aliases:
        add(_normalize_name(alias_value), entity_id)
    return index


def _resolve_entity(conn, raw: str, clean: str, index: dict) -> tuple[int | None, str]:
    """Find the person a cell belongs to.

    Tier 1 is the roster's own slug ref (``external_refs``), which is what the
    roster import recorded. Tier 2 is an exact normalized-name match, but only
    against people already in the roster's segments — a supporting match, never
    a membership decision.
    """
    for candidate in (raw.strip(), clean):
        ref = _slug(candidate)
        if not ref:
            continue
        row = conn.execute(
            "SELECT entity_id FROM external_refs WHERE source=? AND ref_value=?",
            (ROSTER_REF, ref),
        ).fetchone()
        if row is None:
            continue
        entity_id = row[0]
        rejected = conn.execute(
            "SELECT 1 FROM decision_state WHERE entity_id=? AND channel=?"
            " AND status='rejected'",
            (entity_id, ROSTER_REF),
        ).fetchone()
        if rejected:
            continue
        return entity_id, f"roster ref {ref}"

    hits = index.get(_normalize_name(clean), [])
    if len(hits) == 1:
        return hits[0], "name match in roster segments"
    if len(hits) > 1:
        return None, f"ambiguous name, {len(hits)} candidates"
    return None, "no roster ref or name match"


def backfill(db_path=None, grid=None, dry_run: bool = False) -> dict:
    """Load affiliations, name claims and review rows from the roster grid."""
    grid_path = Path(grid)
    conn = store.connect(db_path)
    stats: Counter = Counter()
    unresolved: list[tuple[str, str, str]] = []
    review: list[tuple[int, str, str]] = []
    try:
        rows = list(csv.reader(grid_path.open(newline="", encoding="utf-8")))
        with conn:
            source_id = register_source(
                conn,
                name=SOURCE_NAME,
                kind=SOURCE_KIND,
                url=SOURCE_URL,
                path=grid_path,
                fetched_at="2026-09-22",
                note="Published beatrack IDL historical roster; 71 seasons 2023-1911",
            )
            for sid in (ALUMNI_SEGMENT, STAFF_SEGMENT):
                store.ensure_segment(conn, sid)
            index = _name_index(conn)

            header = rows[0]
            for col, label in enumerate(header):
                if not label.strip():
                    continue
                season_year = _season_year(label)
                band: str | None = None
                role: str | None = None
                section: str | None = None
                slot = 0
                for row_index, row in enumerate(rows[1:], start=1):
                    cell = row[col].strip() if col < len(row) else ""
                    if not cell:
                        continue
                    band_label = cell.lower()
                    if band_label in BANDS:
                        band = cell
                        role, section = BANDS[band_label]
                        slot = 0
                        continue
                    if band is None:
                        continue
                    slot += 1
                    source_ref = f"r{row_index}:c{col}"
                    if season_year is None:
                        stats["bad_header"] += 1
                        unresolved.append((source_ref, cell, "header has no year"))
                        continue
                    parsed = parse_cell(cell)
                    name = parsed["name"]
                    if _is_placeholder(name):
                        stats["placeholder"] += 1
                        unresolved.append((source_ref, cell, "placeholder, no name"))
                        continue
                    entity_id, how = _resolve_entity(conn, cell, name, index)
                    if entity_id is None:
                        stats["unresolved"] += 1
                        unresolved.append((source_ref, name, how))
                        continue
                    stats["matched"] += 1
                    if not dry_run:
                        cursor = conn.execute(
                            "INSERT OR IGNORE INTO affiliations (entity_id,"
                            " ensemble_key, role_key, season_year, season_label,"
                            " section_key, slot, source_id, source_ref, raw_text)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (
                                entity_id,
                                ENSEMBLE_KEY,
                                role,
                                season_year,
                                label.strip(),
                                section,
                                slot,
                                source_id,
                                source_ref,
                                cell,
                            ),
                        )
                        if cursor.rowcount:
                            stats["affiliations"] += 1
                        else:
                            stats["duplicate"] += 1
                        for annotation in parsed["annotations"]:
                            if annotation["kind"] in {
                                "nickname",
                                "maiden_name",
                                "aka",
                                "name",
                            }:
                                created = conn.execute(
                                    "INSERT OR IGNORE INTO aliases (entity_id,"
                                    " alias_type, alias_value, source, position,"
                                    " confidence, observed_at, source_ref)"
                                    " VALUES (?,?,?,?,?,?,date('now'),?)",
                                    (
                                        entity_id,
                                        annotation["kind"],
                                        annotation["value"],
                                        ROSTER_REF,
                                        0,
                                        annotation["confidence"],
                                        source_ref,
                                    ),
                                ).rowcount
                                stats["claims" if created else "claim_dup"] += 1
                            else:
                                conn.execute(
                                    "INSERT INTO decision_state (entity_id,"
                                    " channel, status, reason, source, observed_at)"
                                    " VALUES (?,?,?,?,?,date('now'))",
                                    (
                                        entity_id,
                                        ANNOTATION_CHANNEL,
                                        "pending",
                                        f"{annotation['kind']}:"
                                        f" {annotation['value']} ({source_ref})",
                                        SOURCE_NAME,
                                    ),
                                )
                                stats["review"] += 1
                                review.append(
                                    (entity_id, annotation["value"], source_ref)
                                )
                    else:
                        for annotation in parsed["annotations"]:
                            stats[
                                "claim" if annotation["kind"] != "review" else "review"
                            ] += 1

            if not dry_run:
                for source_ref, display_name, why in unresolved:
                    conn.execute(
                        "INSERT OR IGNORE INTO unresolved_identities"
                        " (platform, source_id, display_name, last_seen)"
                        " VALUES (?,?,?,date('now'))",
                        ("idl-roster-cell", source_ref, f"{display_name} [{why}]"),
                    )
            stats["unresolved_rows"] = len(unresolved)
    finally:
        conn.close()
    return {
        "stats": dict(stats),
        "unresolved": unresolved[:40],
        "review": review[:20],
    }


NOTE_RE = re.compile(
    r"IDL roster:\s*(?P<sections>[^;]+);\s*(?P<years>[^;]+)(?:;\s*(?P<rest>.*))?$",
    re.S,
)
YEAR_RE = re.compile(r"(\d{4})\s*(?:[-\u2013]\s*(\d{4}))?")
NOTE_SECTIONS = {
    "snare": "snares",
    "tenors": "tenors",
    "basses": "basses",
    "cymbals": "cymbals",
    "keyboard": "glockenspiels",
    "timpani": "timpani",
}


def parse_note(notes: str) -> dict | None:
    """Read an ``IDL roster: <sections>; <years>`` note into its parts."""
    match = NOTE_RE.search(notes or "")
    if not match:
        return None
    sections: set[str] = set()
    role = None
    for token in re.split(r"[/,]", match.group("sections")):
        label = token.strip().lower()
        if label == "staff":
            role = "staff"
        elif label in NOTE_SECTIONS:
            sections.add(NOTE_SECTIONS[label])
        elif label:
            sections.add(label)
    years: set[int] = set()
    for start, end in YEAR_RE.findall(match.group("years")):
        years.update(range(int(start), int(end) + 1) if end else {int(start)})
    return {"sections": sections, "role": role, "years": years,
            "rest": (match.group("rest") or "").strip()}


def retire_notes(db_path=None, dry_run: bool = True) -> dict:
    """Strip the roster prose from notes, but only where it now matches.

    A note is retired only when its sections and seasons agree exactly with the
    affiliations backfilled from the same sheet; anything else is reported and
    left alone, so the prose cannot outlive the claim it contradicts.
    """
    conn = store.connect(db_path)
    stats: Counter = Counter()
    mismatches: list[tuple] = []
    try:
        with conn:
            row = conn.execute(
                "SELECT id FROM sources WHERE name=?", (SOURCE_NAME,)
            ).fetchone()
            source_id = row[0] if row else None
            entities = conn.execute(
                "SELECT id, display_name, notes FROM entities WHERE notes LIKE ?",
                ("%IDL roster:%",),
            ).fetchall()
            unresolved_names = {
                _normalize_name(row[0].split(" [")[0])
                for row in conn.execute(
                    "SELECT display_name FROM unresolved_identities WHERE"
                    " platform='idl-roster-cell'"
                )
                if row[0]
            }
            for entity_id, display_name, notes in entities:
                parsed = parse_note(notes)
                if parsed is None:
                    mismatches.append((entity_id, display_name, notes, "unparsed"))
                    continue
                # A note can carry more than one roster segment (two import runs
                # appended to some people); fold them into one claim.
                while parsed["rest"]:
                    nxt = parse_note(parsed["rest"])
                    if nxt is None:
                        break
                    parsed["sections"] |= nxt["sections"]
                    parsed["years"] |= nxt["years"]
                    parsed["role"] = parsed["role"] or nxt["role"]
                    parsed["rest"] = nxt["rest"]
                if source_id is None:
                    mismatches.append((entity_id, display_name, notes, "no source"))
                    continue
                affiliations = conn.execute(
                    "SELECT DISTINCT role_key, season_year, section_key FROM"
                    " affiliations WHERE entity_id=? AND source_id=?",
                    (entity_id, source_id),
                ).fetchall()
                years = {r[1] for r in affiliations}
                sections = {r[2] for r in affiliations if r[2]}
                roles = {r[0] for r in affiliations}
                # The note may be the narrower side of a fold, or a span summary
                # of the same seasons; either way the store must dominate it.
                subset = parsed["years"] <= years
                span_summary = (
                    bool(parsed["years"])
                    and bool(years)
                    and years <= parsed["years"]
                    and min(parsed["years"]) == min(years)
                    and max(parsed["years"]) == max(years)
                )
                if (
                    _normalize_name(display_name or "") in unresolved_names
                ):
                    mismatches.append(
                        (entity_id, display_name, notes, "has unresolved roster cells")
                    )
                    continue
                if (
                    not parsed["sections"] <= sections
                    or not (subset or span_summary)
                    or (parsed["role"] and parsed["role"] not in roles)
                ):
                    mismatches.append(
                        (
                            entity_id,
                            display_name,
                            notes,
                            f"note {sorted(parsed['years'])}/{sorted(parsed['sections'])}"
                            f" vs store {sorted(years)}/{sorted(sections)}",
                        )
                    )
                    continue
                if not dry_run:
                    conn.execute(
                        "UPDATE entities SET notes=?, updated_at=datetime('now')"
                        " WHERE id=?",
                        (parsed["rest"] or "", entity_id),
                    )
                stats["retired_kept_text" if parsed["rest"] else "retired"] += 1
            if not dry_run and stats["retired"] + stats["retired_kept_text"]:
                conn.execute(
                    "INSERT INTO audit_log (resource_name, action, delta) VALUES"
                    " (?,?,?)",
                    (
                        "entities.notes",
                        "RETIRE_ROSTER_PROSE",
                        f"retired {stats['retired']} notes (kept text on"
                        f" {stats['retired_kept_text']}); mismatches"
                        f" {len(mismatches)}",
                    ),
                )
    finally:
        conn.close()
    stats["mismatches"] = len(mismatches)
    return {"stats": dict(stats), "mismatches": mismatches[:25]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill affiliations from the beatrack roster grid"
    )
    parser.add_argument("--grid", help="path to the roster grid CSV")
    parser.add_argument("--db", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--retire-notes",
        action="store_true",
        help="strip the IDL roster prose now that affiliations carry it",
    )
    args = parser.parse_args(argv)

    if args.retire_notes:
        result = retire_notes(db_path=args.db, dry_run=args.dry_run)
        print("retire roster prose" + (" (dry run)" if args.dry_run else ""))
        for key, value in sorted(result["stats"].items()):
            print(f"  {key:20s} {value}")
        if result["mismatches"]:
            print("  still disagreeing with the store (left in place):")
            for entity_id, display, notes, why in result["mismatches"]:
                print(f"    {entity_id} {display!r}: {why}")
        return 0

    if not args.grid:
        parser.error("--grid is required unless --retire-notes is given")
    result = backfill(db_path=args.db, grid=args.grid, dry_run=args.dry_run)
    print("affiliations backfill" + (" (dry run)" if args.dry_run else ""))
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:16s} {value}")
    conn = store.connect(args.db)
    total = conn.execute("SELECT count(*) FROM affiliations").fetchone()[0]
    people = conn.execute("SELECT count(DISTINCT entity_id) FROM affiliations").fetchone()[
        0
    ]
    conn.close()
    print(f"  {'in store':16s} {total} affiliations over {people} people")
    if result["review"]:
        print("  review queue:")
        for entity_id, value, source_ref in result["review"]:
            print(f"    {source_ref} entity {entity_id}: {value}")
    if result["unresolved"]:
        print(f"  unresolved (first {len(result['unresolved'])}):")
        for source_ref, display, why in result["unresolved"]:
            print(f"    {source_ref} {display!r} — {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
