"""Derive the 'needs a live email' research backlog from the store.

A segment member needs a live email when they have **no** email contact point,
or every email they have is currently non-live (bounced or invite-pending) in
``external_status``. This replaces the hand-maintained illini CSV, which had
already drifted from the store.

Reachability is per person (Contact-Completeness): a single email with any other
status makes the person reachable.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

from ...store import connect

SEGMENT = "illini-drumline-alumni"
BAD_STATUSES = ("bouncing", "invited")
HEADER = [
    "Person",
    "Person_ID",
    "Tracker_IDs",
    "Flagged_Addresses",
    "Known_Addresses",
    "Notes",
]


def _segment_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM segments WHERE name = ?", (SEGMENT,)).fetchone()
    if row is None:
        raise SystemExit(f"segment not found: {SEGMENT}")
    return row["id"]


def _refs(conn: sqlite3.Connection, entity_id: int, source: str) -> list[str]:
    return [
        row["ref_value"]
        for row in conn.execute(
            "SELECT ref_value FROM external_refs WHERE entity_id = ? AND source = ?",
            (entity_id, source),
        )
    ]


def _emails(conn: sqlite3.Connection, entity_id: int) -> list[tuple[str, str]]:
    """Return (address, latest_status) for each email contact point."""
    result = []
    for point in conn.execute(
        "SELECT value FROM contact_points WHERE entity_id = ? AND kind = 'email'"
        " ORDER BY is_primary DESC, id",
        (entity_id,),
    ):
        status = conn.execute(
            "SELECT status FROM external_status WHERE entity_id = ? AND lower(address) = lower(?)"
            " ORDER BY observed_at DESC, id DESC LIMIT 1",
            (entity_id, point["value"]),
        ).fetchone()
        result.append((point["value"], status["status"] if status else ""))
    return result


def _display_name(conn: sqlite3.Connection, entity_id: int) -> str:
    row = conn.execute(
        "SELECT display_name, first_name, last_name FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()
    joined = " ".join(part for part in (row["first_name"], row["last_name"]) if part)
    return (row["display_name"] or joined).strip() or "(unnamed)"


def _person_id(conn: sqlite3.Connection, entity_id: int) -> str:
    refs = _refs(conn, entity_id, "master_person_id")
    return refs[0] if refs else f"P9{entity_id}"


def build_rows(conn: sqlite3.Connection) -> list[dict]:
    segment = _segment_id(conn)
    members = [
        row["entity_id"]
        for row in conn.execute(
            "SELECT entity_id FROM segment_members WHERE segment_id = ? ORDER BY entity_id",
            (segment,),
        )
    ]
    rows = []
    for entity_id in members:
        emails = _emails(conn, entity_id)
        if any(status not in BAD_STATUSES for _, status in emails):
            continue  # has at least one live email
        flagged = [address for address, status in emails if status in BAD_STATUSES]
        if not emails:
            note = "No email on file"
        else:
            labels = ", ".join(sorted({status or "unknown" for _, status in emails}))
            note = f"Only non-live email(s): {labels}"
        rows.append(
            {
                "Person": _display_name(conn, entity_id),
                "Person_ID": _person_id(conn, entity_id),
                "Tracker_IDs": ", ".join(
                    sorted(
                        _refs(conn, entity_id, "tracker_id"), key=lambda v: (len(v), v)
                    )
                ),
                "Flagged_Addresses": ", ".join(flagged),
                "Known_Addresses": ", ".join(address for address, _ in emails),
                "Notes": note,
            }
        )
    return rows


def derive_needs_live_email(out_path, db_path=None) -> int:
    conn = connect(db_path)
    try:
        rows = build_rows(conn)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive the needs-live-email backlog from the store"
    )
    parser.add_argument("--out", required=True, help="output CSV path")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    count = derive_needs_live_email(args.out, args.db)
    print(f"Wrote {count} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
