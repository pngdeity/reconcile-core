"""Export the drumline member list (person level) from the canonical store.

Ports illini ``working/export_drumline_members.py``. One row per person in the
``illini-drumline-alumni`` segment, with all known emails, phone, verification,
Tracker/Contacts IDs, dump presence, and outreach status. Generated — edit the
store and re-run; do not hand-edit.

Usage:
    uv run python -m reconcile_core.profile.drumline.export_members \
        [--out PATH] [--db PATH] [--quiet]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ...store import store

SEGMENT = "illini-drumline-alumni"

HEADER = [
    "Person_ID",
    "First_Name",
    "Last_Name",
    "Display_Name",
    "Email_Primary",
    "Email_All",
    "Phone",
    "Verification",
    "Tracker_IDs",
    "Contacts_IDs",
    "Dumps_Seen",
    "Reached_Dumps_1_6",
    "Reached_Dump_0",
    "Has_Email",
    "Has_Phone",
    "Tracker_Notes",
    "Needs_First_Outreach",
    "Review_Status",
]


def as_int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**9


def build_rows(conn) -> list[dict]:
    segment_entities = [
        row["entity_id"]
        for row in conn.execute(
            """SELECT sm.entity_id FROM segment_members sm
               JOIN segments s ON s.id = sm.segment_id
               WHERE s.name = ?""",
            (SEGMENT,),
        )
    ]

    def refs(entity_id: int, source: str) -> list[str]:
        return [
            row["ref_value"]
            for row in conn.execute(
                "SELECT ref_value FROM external_refs WHERE entity_id=? AND source=?",
                (entity_id, source),
            )
        ]

    def ref_one(entity_id: int, source: str):
        values = refs(entity_id, source)
        return values[0] if values else None

    rows: list[dict] = []
    for entity_id in segment_entities:
        entity = conn.execute(
            "SELECT first_name, last_name, display_name FROM entities WHERE id=?",
            (entity_id,),
        ).fetchone()

        emails = conn.execute(
            """SELECT value, is_primary, position, id FROM contact_points
               WHERE entity_id=? AND kind='email'
               ORDER BY (position IS NULL), position, id""",
            (entity_id,),
        ).fetchall()
        primary = next((e["value"] for e in emails if e["is_primary"]), None)
        if not primary and emails:
            primary = emails[0]["value"]

        phones = conn.execute(
            """SELECT value FROM contact_points WHERE entity_id=? AND kind='phone'
               ORDER BY (position IS NULL), position, id""",
            (entity_id,),
        ).fetchall()

        outreach = conn.execute(
            "SELECT * FROM drumline_outreach WHERE entity_id=?", (entity_id,)
        ).fetchone()

        person_id = ref_one(entity_id, "master_person_id") or f"P9{entity_id:04d}"
        tracker_ids = sorted(refs(entity_id, "tracker_id"), key=as_int)
        contacts_ids = sorted(refs(entity_id, "google_contacts_id"), key=as_int)

        first = entity["first_name"] or ""
        last = entity["last_name"] or ""
        display = entity["display_name"] or " ".join(p for p in (first, last) if p)

        rows.append(
            {
                "Person_ID": person_id,
                "First_Name": first,
                "Last_Name": last,
                "Display_Name": display,
                "Email_Primary": primary or "",
                "Email_All": ";".join(e["value"] for e in emails),
                "Phone": phones[0]["value"] if phones else "",
                "Verification": outreach["verification"] if outreach else "",
                "Tracker_IDs": ",".join(tracker_ids),
                "Contacts_IDs": ",".join(contacts_ids),
                "Dumps_Seen": outreach["dumps_seen"] if outreach else "",
                "Reached_Dumps_1_6": outreach["reached_dumps_1_6"] if outreach else "",
                "Reached_Dump_0": outreach["reached_dump_0"] if outreach else "",
                "Has_Email": outreach["has_email"]
                if outreach
                else ("Yes" if emails else "No"),
                "Has_Phone": outreach["has_phone"]
                if outreach
                else ("Yes" if phones else "No"),
                "Tracker_Notes": outreach["tracker_notes"] if outreach else "",
                "Needs_First_Outreach": outreach["needs_first_outreach"]
                if outreach
                else "",
                "Review_Status": outreach["review_status"] if outreach else "",
            }
        )

    rows.sort(key=lambda row: row["Person_ID"])
    return rows


def export_members(out_path: Path | str, db_path=None) -> int:
    conn = store.connect(db_path)
    try:
        rows = build_rows(conn)
    finally:
        conn.close()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output CSV path")
    parser.add_argument("--db", default=None, help="contacts store path")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    count = export_members(args.out, db_path=args.db)
    if not args.quiet:
        print(f"Wrote {args.out} ({count} rows, {len(HEADER)} cols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
