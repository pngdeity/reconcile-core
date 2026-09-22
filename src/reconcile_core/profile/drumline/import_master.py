"""Seed the drumline outreach/status overlay from a legacy master list.

Ports illini ``working/import_master.py``. One-time migration input (the legacy
``drumline-master-v2.csv``). Writes ``external_refs(source='master_person_id')``,
``contact_points.is_primary`` from the legacy ``Email_Primary``, and the
``drumline_outreach`` row. Idempotent (upsert on entity_id).

Usage:
    uv run python -m reconcile_core.profile.drumline.import_master \
        --input /path/drumline-master-v2.csv [--db PATH]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ...store import store

GMAIL = ("gmail.com", "googlemail.com")


def norm_email(value: str) -> str:
    return (value or "").strip().lower()


def dot_key(value: str) -> str:
    """Gmail dot-normalized key for matching; otherwise the lowercased address."""
    e = norm_email(value)
    if "@" not in e:
        return e
    local, _, domain = e.rpartition("@")
    if domain in GMAIL:
        local = local.replace(".", "")
    return f"{local}@{domain}"


def split_list(value: str, sep: str) -> list[str]:
    return [p.strip() for p in (value or "").split(sep) if p.strip()]


def _seed_rows(conn, master_csv: Path | str) -> dict:
    email_index: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT entity_id, value FROM contact_points WHERE kind='email'"
    ):
        email_index.setdefault(norm_email(row["value"]), []).append(row["entity_id"])
        email_index.setdefault(dot_key(row["value"]), []).append(row["entity_id"])

    def by_ref(source: str, value: str):
        row = conn.execute(
            "SELECT entity_id FROM external_refs WHERE source=? AND ref_value=?",
            (source, value),
        ).fetchone()
        return row["entity_id"] if row else None

    def resolve(row: dict):
        for cid in split_list(row.get("Contacts_IDs", ""), ","):
            entity_id = by_ref("google_contacts_id", cid)
            if entity_id:
                return entity_id
        for tid in split_list(row.get("Tracker_IDs", ""), ","):
            entity_id = by_ref("tracker_id", tid)
            if entity_id:
                return entity_id
        for email in split_list(row.get("Email_All", ""), ";"):
            for key in (norm_email(email), dot_key(email)):
                if key in email_index:
                    return email_index[key][0]
        return None

    rows = list(csv.DictReader(open(master_csv, newline="", encoding="utf-8")))
    unresolved: list[str] = []
    linked = primary_set = outreach = 0

    for row in rows:
        person_id = (row.get("Person_ID") or "").strip()
        entity_id = resolve(row)
        if entity_id is None:
            unresolved.append(person_id)
            continue
        linked += 1

        conn.execute(
            "INSERT OR IGNORE INTO external_refs (entity_id, source, ref_value) VALUES (?,?,?)",
            (entity_id, "master_person_id", person_id),
        )

        primary = norm_email(row.get("Email_Primary"))
        if primary:
            points = conn.execute(
                "SELECT id, value FROM contact_points WHERE entity_id=? AND kind='email'",
                (entity_id,),
            ).fetchall()
            match = next(
                (p["id"] for p in points if norm_email(p["value"]) == primary), None
            )
            if match:
                conn.execute(
                    "UPDATE contact_points SET is_primary=0 WHERE entity_id=? AND kind='email'",
                    (entity_id,),
                )
                conn.execute(
                    "UPDATE contact_points SET is_primary=1 WHERE id=?", (match,)
                )
                primary_set += 1

        conn.execute(
            """INSERT INTO drumline_outreach
               (entity_id, verification, dumps_seen, reached_dumps_1_6, reached_dump_0,
                has_email, has_phone, tracker_notes, needs_first_outreach, review_status,
                updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(entity_id) DO UPDATE SET
                 verification=excluded.verification,
                 dumps_seen=excluded.dumps_seen,
                 reached_dumps_1_6=excluded.reached_dumps_1_6,
                 reached_dump_0=excluded.reached_dump_0,
                 has_email=excluded.has_email,
                 has_phone=excluded.has_phone,
                 tracker_notes=excluded.tracker_notes,
                 needs_first_outreach=excluded.needs_first_outreach,
                 review_status=excluded.review_status,
                 updated_at=datetime('now')""",
            (
                entity_id,
                row.get("Verification", ""),
                row.get("Dumps_Seen", ""),
                row.get("Reached_Dumps_1_6", ""),
                row.get("Reached_Dump_0", ""),
                row.get("Has_Email", ""),
                row.get("Has_Phone", ""),
                row.get("Tracker_Notes", ""),
                row.get("Needs_First_Outreach", ""),
                row.get("Review_Status", ""),
            ),
        )
        outreach += 1

    return {
        "master_rows": len(rows),
        "linked": linked,
        "unresolved": unresolved,
        "primary_set": primary_set,
        "outreach_rows": outreach,
    }


def seed_outreach(master_csv: Path | str, db_path=None) -> dict:
    """Seed the outreach overlay from a legacy master CSV and commit."""
    conn = store.connect(db_path)
    try:
        result = _seed_rows(conn, master_csv)
        conn.commit()
        return result
    finally:
        conn.close()


run = seed_outreach


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="legacy drumline master CSV")
    parser.add_argument("--db", default=None, help="contacts store path")
    args = parser.parse_args()

    result = seed_outreach(args.input, db_path=args.db)
    print(f"master rows: {result['master_rows']}")
    print(
        f"linked: {result['linked']}  unresolved: {len(result['unresolved'])} {result['unresolved'][:10]}"
    )
    print(f"primary emails set: {result['primary_set']}")
    print(f"drumline_outreach rows: {result['outreach_rows']}")
    return 0 if not result["unresolved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
