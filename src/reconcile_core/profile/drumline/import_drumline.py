"""Drumline membership import: Tracker links, alumni segment, decision state.

Ports illini ``working/import_drumline.py`` onto the canonical store. Inputs
(Tracker.csv and the ``manual_*`` JSONs) carry PII and are passed in, never
bundled. Idempotent.

Usage:
    uv run python -m reconcile_core.profile.drumline.import_drumline \
        --tracker /path/Tracker.csv [--config-dir DIR] [--db PATH]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ...store import store
from . import config as config_mod

ALUMNI_SEGMENT = "illini-drumline-alumni"
SOURCE = "drumline-import"

ENTITY_FIELDS = (
    "display_name",
    "first_name",
    "middle_name",
    "last_name",
    "nickname",
    "org_name",
    "title",
    "department",
    "birthday",
    "notes",
)


def clean(value):
    value = (value or "").strip()
    return value or None


def gcid_entity(conn, gcid):
    if gcid is None or str(gcid).strip() == "":
        return None
    return store.get_entity_by_ref(conn, "google_contacts_id", str(gcid).strip())


def email_entity(conn, email):
    if not email:
        return None
    row = conn.execute(
        "SELECT entity_id FROM contact_points "
        "WHERE kind = 'email' AND lower(value) = lower(?) LIMIT 1",
        (email,),
    ).fetchone()
    return row["entity_id"] if row else None


def name_entity(conn, name):
    if not name:
        return None
    target = name.strip().lower()
    for row in conn.execute(
        "SELECT id, display_name, first_name, last_name FROM entities"
    ):
        full = (
            " ".join(p for p in (row["first_name"], row["last_name"]) if p)
            .strip()
            .lower()
        )
        if target in (full, (row["display_name"] or "").strip().lower()):
            return row["id"]
    return None


def contact_point_for(conn, entity_id, email):
    row = conn.execute(
        "SELECT id FROM contact_points "
        "WHERE entity_id = ? AND kind = 'email' AND lower(value) = lower(?)",
        (entity_id, email),
    ).fetchone()
    return row["id"] if row else None


def apply_merges(conn, merges):
    applied = []
    for merge in merges:
        keep = gcid_entity(conn, merge.get("keep_gcid"))
        drop = gcid_entity(conn, merge.get("merge_gcid"))
        if keep is None or drop is None or keep == drop:
            continue
        ke = conn.execute("SELECT * FROM entities WHERE id = ?", (keep,)).fetchone()
        de = conn.execute("SELECT * FROM entities WHERE id = ?", (drop,)).fetchone()
        for field in ENTITY_FIELDS:
            if not (ke[field] or "") and (de[field] or ""):
                conn.execute(
                    f"UPDATE entities SET {field} = ? WHERE id = ?", (de[field], keep)
                )
        conn.execute(
            "UPDATE contact_points SET entity_id = ? WHERE entity_id = ?", (keep, drop)
        )
        conn.execute(
            "UPDATE decision_state SET entity_id = ? WHERE entity_id = ?", (keep, drop)
        )
        for alias in conn.execute(
            "SELECT * FROM aliases WHERE entity_id = ?", (drop,)
        ).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO aliases "
                "(entity_id, alias_type, alias_value, source, position) VALUES (?, ?, ?, ?, ?)",
                (
                    keep,
                    alias["alias_type"],
                    alias["alias_value"],
                    alias["source"],
                    alias["position"],
                ),
            )
        for member in conn.execute(
            "SELECT * FROM segment_members WHERE entity_id = ?", (drop,)
        ).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO segment_members (segment_id, entity_id, added_at) "
                "VALUES (?, ?, ?)",
                (member["segment_id"], keep, member["added_at"]),
            )
        conn.execute("DELETE FROM entities WHERE id = ?", (drop,))
        applied.append((merge.get("keep_gcid"), merge.get("merge_gcid")))
    return applied


def import_tracker(conn, tracker_path: Path | str):
    rows = list(csv.DictReader(open(tracker_path, newline="", encoding="utf-8")))
    segment = store.ensure_segment(conn, ALUMNI_SEGMENT)
    created = linked = 0
    for row in rows:
        tid = clean(row.get("ID"))
        entity_id = (
            store.get_entity_by_ref(conn, "tracker_id", tid)
            or gcid_entity(conn, row.get("Contacts ID"))
            or email_entity(conn, row.get("Email"))
        )
        if entity_id is None:
            entity_id = store.create_entity(
                conn,
                type="person",
                display_name=" ".join(
                    p
                    for p in (clean(row.get("First Name")), clean(row.get("Last Name")))
                    if p
                )
                or None,
                first_name=clean(row.get("First Name")),
                middle_name=clean(row.get("Middle")),
                last_name=clean(row.get("Last Name")),
            )
            created += 1
        else:
            linked += 1
        store.add_external_ref(conn, entity_id, "tracker_id", tid)
        entity = conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        for field, value in (
            ("first_name", clean(row.get("First Name"))),
            ("middle_name", clean(row.get("Middle"))),
            ("last_name", clean(row.get("Last Name"))),
        ):
            if not (entity[field] or "") and value:
                conn.execute(
                    f"UPDATE entities SET {field} = ? WHERE id = ?", (value, entity_id)
                )
        # The Tracker's Verification and Notes belong in drumline_outreach, their
        # single home: the old tracker_verification / tracker_notes alias carriers
        # were retired 2026-09-23. An existing non-empty value wins, because later
        # passes (idl-roster, dedup, name resolutions) hold the fresher truth.
        if clean(row.get("Verification")):
            conn.execute(
                "INSERT INTO drumline_outreach (entity_id, verification,"
                " verification_source) VALUES (?, ?, ?)"
                " ON CONFLICT(entity_id) DO UPDATE SET"
                " verification = excluded.verification,"
                " verification_source = excluded.verification_source,"
                " updated_at = datetime('now')"
                " WHERE ifnull(drumline_outreach.verification, '') = ''",
                (entity_id, row["Verification"].strip(), SOURCE),
            )
        if clean(row.get("Notes")):
            conn.execute(
                "INSERT INTO drumline_outreach (entity_id, tracker_notes,"
                " notes_source) VALUES (?, ?, ?)"
                " ON CONFLICT(entity_id) DO UPDATE SET"
                " tracker_notes = excluded.tracker_notes,"
                " notes_source = excluded.notes_source,"
                " updated_at = datetime('now')"
                " WHERE ifnull(drumline_outreach.tracker_notes, '') = ''",
                (entity_id, row["Notes"].strip(), SOURCE),
            )
        store.add_segment_member(conn, segment, entity_id)
    return rows, created, linked


def import_decision_state(conn, *, address_map, invite, blocked, hold):
    added = skipped = 0

    def add(entity_id, status, channel, cp_id, reason, observed=None):
        nonlocal added, skipped
        if entity_id is None:
            return
        exists = conn.execute(
            "SELECT 1 FROM decision_state WHERE entity_id = ? AND status = ? "
            "AND ifnull(reason, '') = ifnull(?, '')",
            (entity_id, status, reason),
        ).fetchone()
        if exists:
            skipped += 1
            return
        store.add_decision_state(
            conn,
            entity_id,
            status,
            channel=channel,
            contact_point_id=cp_id,
            reason=reason,
            source=SOURCE,
            observed_at=observed,
        )
        added += 1

    for email, meta in (address_map or {}).items():
        if email.startswith("_"):
            continue
        tracker_ref = meta.get("tracker_id")
        entity_id = (
            store.get_entity_by_ref(conn, "tracker_id", str(tracker_ref))
            if tracker_ref
            else None
        ) or email_entity(conn, email)
        if entity_id is None:
            continue
        cp = contact_point_for(conn, entity_id, email)
        if cp is None:
            cp = store.add_contact_point(
                conn, entity_id, "email", email, source="manual_address_map"
            )
        add(
            entity_id,
            "additional_address_confirmed",
            "manual_address_map",
            cp,
            meta.get("note"),
        )

    for item in invite or []:
        email = item.get("email")
        entity_id = email_entity(conn, email) or name_entity(conn, item.get("person"))
        cp = contact_point_for(conn, entity_id, email) if entity_id else None
        add(
            entity_id,
            "invite_required",
            "google_groups",
            cp,
            item.get("reason"),
            item.get("date"),
        )

    for item in blocked or []:
        email = item.get("email")
        entity_id = email_entity(conn, email) or name_entity(conn, item.get("person"))
        cp = contact_point_for(conn, entity_id, email) if entity_id else None
        add(
            entity_id,
            "blocked",
            "google_groups",
            cp,
            item.get("reason"),
            item.get("date"),
        )

    for item in hold or []:
        email = item.get("email")
        entity_id = email_entity(conn, email) or name_entity(conn, item.get("person"))
        cp = contact_point_for(conn, entity_id, email) if entity_id else None
        add(
            entity_id, "held", "google_groups", cp, item.get("reason"), item.get("date")
        )

    return added, skipped


def run(tracker, db_path=None, config=None) -> dict:
    """Apply merges, import Tracker + decision state. Returns stats."""
    conn = store.connect(db_path)
    try:
        applied = apply_merges(conn, config_mod.merges(config))
        rows, created, linked = import_tracker(conn, tracker)
        d_added, d_skipped = import_decision_state(
            conn,
            address_map=config_mod.address_map(config),
            invite=config_mod.invite_required(config),
            blocked=config_mod.blocked(config),
            hold=config_mod.hold(config),
        )
        conn.commit()
        segment = store.ensure_segment(conn, ALUMNI_SEGMENT)
        seg_count = conn.execute(
            "SELECT COUNT(*) AS n FROM segment_members WHERE segment_id = ?",
            (segment,),
        ).fetchone()["n"]
        tracker_refs = conn.execute(
            "SELECT COUNT(*) AS n FROM external_refs WHERE source = 'tracker_id'"
        ).fetchone()["n"]
        return {
            "tracker_rows": len(rows),
            "linked": linked,
            "created": created,
            "merges_applied": len(applied),
            "tracker_refs": tracker_refs,
            "decision_added": d_added,
            "decision_skipped": d_skipped,
            "segment_members": seg_count,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", required=True, help="Tracker.csv path")
    parser.add_argument("--config-dir", default=None, help="drumline config directory")
    parser.add_argument("--db", default=None, help="contacts store path")
    args = parser.parse_args()

    stats = run(args.tracker, db_path=args.db, config=args.config_dir)
    for key, value in stats.items():
        print(f"{key:18s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
