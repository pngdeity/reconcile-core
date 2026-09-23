"""Load the audition result documents into ``affiliations``.

The audition documents are nested **lists**, not grids, so the roster's column
walker does not apply. The versioned extract is one content line per source line,
``pN:lN<TAB>text``, which is what ``source_ref`` points at.

Decisions recorded 2026-09-23 (``docs/MEMBERSHIP-SCHEMA.md``):

* ``season_year`` = the audition's calendar year: a season labelled ``YYYY``
  opens the following August and its audition is held in April ``YYYY``, so the
  2025 final results are ``season_year = 2025`` and ``season_label = '2025'``.
* ``Kicker`` is **not an instrument** — it is the seventh bass drum, a position
  inside ``basses``. It is captured as ``slot_label`` with ``slot`` NULL, never
  as its own section or role.
* Bass positions keep the source's own numbering (``0``-``5``); sections without
  numbering carry no slot.
* The document is authoritative for membership, so its rows arrive with
  ``review_status = 'Confirmed via audition results'``.

Usage:

    uv run python -m reconcile_core.profile.drumline.audition_affiliations \
        [--text PATH] [--db PATH] [--dry-run] [--create-missing]
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from ...store import store
from .affiliations import (
    ENSEMBLE_KEY,
    _clean_name,
    _is_placeholder,
    _name_index,
    _resolve_entity,
)

SOURCE_NAME = "audition-2025-results"
PLATFORM = "audition-2025-cell"
SEASON_YEAR = 2025
SEASON_LABEL = "2025"
REVIEW_STATUS = "Confirmed via audition results"
DEFAULT_TEXT = (
    # pngdeity/{incubating/reconcile-core, active/illini-drumline-contacts-alumni}:
    # the illini repo is a sibling of the checkout, so the source lives five
    # levels up from this file plus the repo names.
    Path(__file__).resolve().parents[6]
    / "active"
    / "illini-drumline-contacts-alumni"
    / "source"
    / "audition-2025-results.txt"
)

# Source label -> (role_key, section_key). `Staff` is a role, never a section.
SECTIONS: dict[str, tuple[str, str | None]] = {
    "snare": ("member", "snares"),
    "tenors": ("member", "tenors"),
    "bass": ("member", "basses"),
    "cymbals": ("member", "cymbals"),
    "undergraduate staff": ("staff", None),
    "staff": ("staff", None),
}
NAME_LINE = re.compile(r"^[A-Z][A-Za-z'\u2019.\-]*(?:\s+[A-Z][A-Za-z'\u2019.\-]*){0,3}$")
SLOT_LINE = re.compile(r"^(?P<slot>\d{1,2}|kicker)\s*[-\u2013\u2014]\s*(?P<name>.+)$", re.IGNORECASE)


def parse_document(text: str) -> list[dict]:
    """One record per person line: ref, raw, name, role, section, slot, slot_label."""
    records: list[dict] = []
    current: tuple[str, str | None] | None = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        ref, _, body = line.partition("\t")
        body = body.strip()
        if not body:
            continue
        key = body.lower().rstrip(":").strip()
        if key in SECTIONS:
            current = SECTIONS[key]
            continue
        if current is None:
            continue
        role, section = current
        slot: int | None = None
        slot_label = ""
        name = body
        # Bass positions are numbered or named (`0 - Name`, `Kicker - Name`), so
        # the slot form is checked before the plain-name gate.
        match = SLOT_LINE.match(body) if section == "basses" else None
        if match:
            token = match.group("slot")
            candidate = match.group("name").strip()
            if NAME_LINE.match(candidate):
                name = candidate
                if token.isdigit():
                    slot = int(token)
                else:
                    slot_label = token.capitalize()
            else:
                match = None
        if match is None and not NAME_LINE.match(body):
            # Persons are consecutive inside a block; the first prose line ends it.
            current = None
            continue
        records.append(
            {
                "ref": ref,
                "raw": body,
                "name": name,
                "role": role,
                "section": section,
                "slot": slot,
                "slot_label": slot_label,
            }
        )
    return records


def _unresolved(conn, ref: str, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO unresolved_identities"
        " (platform, source_id, display_name, last_seen)"
        " VALUES (?,?,?,datetime('now'))",
        (PLATFORM, ref, name),
    )


def _create_member(conn, name: str, segment_id: int) -> int:
    """Create a confirmed member who has no entity yet (document is authoritative)."""
    parts = name.split()
    entity_id = store.create_entity(
        conn,
        type="person",
        display_name=name,
        first_name=parts[0],
        last_name=parts[-1] if len(parts) > 1 else "",
        middle_name=" ".join(parts[1:-1]) if len(parts) > 2 else "",
    )
    ref = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    store.add_external_ref(conn, entity_id, "audition-2025", ref)
    store.add_segment_member(conn, segment_id, entity_id)
    conn.execute(
        "INSERT OR IGNORE INTO drumline_outreach (entity_id, verification,"
        " review_status, has_email, has_phone) VALUES (?, 'Verified', ?, 'No', 'No')",
        (entity_id, REVIEW_STATUS),
    )
    return entity_id


def backfill(db_path=None, text=None, dry_run: bool = False, create_missing: bool = False) -> dict:
    path = Path(text) if text else DEFAULT_TEXT
    records = parse_document(path.read_text(encoding="utf-8"))
    conn = store.connect(db_path)
    stats: Counter = Counter()
    created: list[str] = []
    try:
        row = conn.execute("SELECT id FROM sources WHERE name = ?", (SOURCE_NAME,)).fetchone()
        if row is None:
            raise SystemExit(f"source not registered in the store: {SOURCE_NAME}")
        source_id = row[0]
        segment_id = store.ensure_segment(conn, "illini-drumline-alumni")
        index = _name_index(conn)
        for record in records:
            stats["lines"] += 1
            name = _clean_name(record["name"])
            if _is_placeholder(name):
                stats["placeholder"] += 1
                if not dry_run:
                    _unresolved(conn, record["ref"], name)
                continue
            entity_id, _how = _resolve_entity(conn, record["raw"], name, index)
            if entity_id is None and create_missing:
                if dry_run:
                    stats["would_create"] += 1
                    created.append(name)
                    continue
                entity_id = _create_member(conn, name, segment_id)
                index.setdefault(name.lower(), []).append(entity_id)
                created.append(name)
            if entity_id is None:
                stats["unresolved"] += 1
                if not dry_run:
                    _unresolved(conn, record["ref"], name)
                continue
            stats["matched"] += 1
            if not dry_run:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO affiliations (entity_id, ensemble_key,"
                    " role_key, season_year, season_label, section_key, slot,"
                    " slot_label, source_id, source_ref, raw_text, review_status)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        entity_id,
                        ENSEMBLE_KEY,
                        record["role"],
                        SEASON_YEAR,
                        SEASON_LABEL,
                        record["section"],
                        record["slot"],
                        record["slot_label"],
                        source_id,
                        record["ref"],
                        record["raw"],
                        REVIEW_STATUS,
                    ),
                )
                stats["affiliations" if cursor.rowcount else "duplicate"] += 1
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    stats["created"] = len(created)
    result = dict(stats)
    for key in ("matched", "unresolved", "placeholder", "affiliations", "duplicate",
                "would_create"):
        result.setdefault(key, 0)
    result["created_names"] = created
    # Invariant: every person line lands somewhere — a row, a duplicate, or a queue.
    result["resolved_lines"] = (
        result.get("matched", 0)
        + result.get("unresolved", 0)
        + result.get("placeholder", 0)
        + result.get("would_create", 0)
    )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load the audition results into affiliations")
    parser.add_argument("--text", default=None, help="versioned extract (pN:lN<TAB>text)")
    parser.add_argument("--db", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create-missing", action="store_true",
                        help="create confirmed members who have no entity yet")
    args = parser.parse_args(argv)

    result = backfill(db_path=args.db, text=args.text, dry_run=args.dry_run,
                      create_missing=args.create_missing)
    print(f"person lines: {result.get('lines', 0)}"
          f"  matched: {result.get('matched', 0)}"
          f"  affiliations: {result.get('affiliations', 0)}"
          f"  duplicates: {result.get('duplicate', 0)}"
          f"  unresolved: {result.get('unresolved', 0)}")
    print(f"invariant: {result.get('resolved_lines', 0)} of {result.get('lines', 0)} lines resolved"
          f"  (matched {result.get('matched', 0)} + unresolved {result.get('unresolved', 0)}"
          f" + placeholder {result.get('placeholder', 0)})")
    if result.get("created_names"):
        print(f"new members: {len(result['created_names'])} — {result['created_names']}")
    if args.dry_run:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
