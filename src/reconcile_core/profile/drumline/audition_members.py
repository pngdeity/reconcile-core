"""Apply the versioned audition-results membership config to the store.

Reads ``var/drumline/audition_members.json`` (PII; git-ignored):

```json
{
  "source": "audition-2025",
  "name_fills": [
    {"entity_id": 1469, "email": "aaron.colon2024@example.com",
     "first_name": "Aaron", "last_name": "Colon", "display_name": "Aaron Colon"}
  ],
  "new_members": [
    {"first_name": "Shrenik", "last_name": "Balaji", "display_name": "Shrenik Balaji"}
  ]
}
```

- **name_fills:** resolve the entity by email contact point (preferred) or
  ``entity_id``, then set only the currently-empty name fields; a differing
  non-empty value is reported as a conflict and left alone.
- **new_members:** create a person entity, anchor it with a ``<source>`` external
  ref (the idempotency key), add it to the alumni segment, and seed an outreach
  row (``verification = Verified``).

Idempotent. Usage:

    uv run python -m reconcile_core.profile.drumline.audition_members \
        [--config-dir DIR] [--db PATH]
"""

from __future__ import annotations

import argparse
import re

from ...store import store
from . import config as config_mod

SEGMENT = "illini-drumline-alumni"
DEFAULT_SOURCE = "audition"
NAME_FIELDS = ("first_name", "middle_name", "last_name", "nickname", "display_name")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _resolve(conn, entry):
    email = (entry.get("email") or "").strip().lower()
    if email:
        row = conn.execute(
            "SELECT entity_id FROM contact_points"
            " WHERE kind = 'email' AND lower(value) = ? ORDER BY id LIMIT 1",
            (email,),
        ).fetchone()
        if row:
            return row["entity_id"]
    return entry.get("entity_id")


def _apply_name_fills(conn, entries) -> tuple[int, list[str]]:
    applied = 0
    conflicts: list[str] = []
    for entry in entries:
        entity_id = _resolve(conn, entry)
        label = (
            entry.get("display_name") or entry.get("email") or entry.get("entity_id")
        )
        if entity_id is None:
            conflicts.append(f"unresolved: {label}")
            continue
        row = conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if row is None:
            conflicts.append(f"no entity {entity_id}: {label}")
            continue
        updates = {}
        for field in NAME_FIELDS:
            value = entry.get(field)
            if not value:
                continue
            current = row[field]
            if current and current != value:
                conflicts.append(f"{label}: {field} already {current!r}, not {value!r}")
                continue
            if current != value:
                updates[field] = value
        if updates:
            columns = ", ".join(f"{field} = ?" for field in updates)
            conn.execute(
                f"UPDATE entities SET {columns} WHERE id = ?",
                (*updates.values(), entity_id),
            )
            applied += 1
    return applied, conflicts


def _has_point(conn, entity_id: int, kind: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM contact_points WHERE entity_id = ? AND kind = ? LIMIT 1",
            (entity_id, kind),
        ).fetchone()
        is not None
    )


def _apply_new_members(conn, entries, source: str) -> int:
    segment_id = store.ensure_segment(conn, SEGMENT)
    created = 0
    for entry in entries:
        display = entry.get("display_name") or " ".join(
            part for part in (entry.get("first_name"), entry.get("last_name")) if part
        )
        ref = _slug(display) or _slug(entry.get("email", ""))
        if not ref:
            continue
        if store.get_entity_by_ref(conn, source, ref) is not None:
            continue

        entity_id = store.create_entity(
            conn,
            type="person",
            display_name=display,
            first_name=entry.get("first_name", ""),
            middle_name=entry.get("middle_name", ""),
            last_name=entry.get("last_name", ""),
            nickname=entry.get("nickname", ""),
            notes=entry.get("notes", ""),
        )
        store.add_external_ref(conn, entity_id, source, ref)
        store.add_segment_member(conn, segment_id, entity_id)
        conn.execute(
            "INSERT OR IGNORE INTO drumline_outreach"
            " (entity_id, verification, has_email, has_phone, review_status)"
            " VALUES (?, 'Verified', ?, ?, 'Confirmed via audition results')",
            (
                entity_id,
                "Yes" if _has_point(conn, entity_id, "email") else "No",
                "Yes" if _has_point(conn, entity_id, "phone") else "No",
            ),
        )
        created += 1
    return created


def apply_audition_members(db_path=None, config=None) -> dict:
    data = config_mod.audition_members(config) or {}
    source = data.get("source") or DEFAULT_SOURCE
    conn = store.connect(db_path)
    try:
        with conn:
            fills, conflicts = _apply_name_fills(conn, data.get("name_fills") or [])
            created = _apply_new_members(conn, data.get("new_members") or [], source)
    finally:
        conn.close()
    return {
        "name_fills_applied": fills,
        "new_members_created": created,
        "conflicts": conflicts,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Apply the audition-members config")
    parser.add_argument("--config-dir")
    parser.add_argument("--db")
    args = parser.parse_args(argv)

    result = apply_audition_members(db_path=args.db, config=args.config_dir)
    print("Audition members applied")
    print(f"  name fills applied:  {result['name_fills_applied']}")
    print(f"  new members created: {result['new_members_created']}")
    for conflict in result["conflicts"]:
        print(f"  conflict: {conflict}")
    return 1 if result["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
