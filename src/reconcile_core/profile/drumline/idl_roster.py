"""Apply the IDL historical-roster membership config to the store.

Reads ``var/drumline/idl_roster.json`` (PII; git-ignored), built by the illini
``working/build_idl_roster_config.py`` from the beatrack.com roster. Shape:

```json
{
  "source": "idl-roster",
  "verification": "Roster-derived",
  "alumni_segment": "illini-drumline-alumni",
  "staff_segment": "idl-staff",
  "segment_additions": [{"entity_id": 318, "matched_name": "David Schroeder",
                         "sections": "Snare", "years": "1970,1971"}],
  "new_members": [{"first_name": "Akira", "last_name": "Robles",
                   "display_name": "Akira Robles", "notes": "IDL roster: ..."}],
  "staff_members": [{"first_name": "Fred", "last_name": "Fairchild", ...}],
  "name_aliases": [{"entity_id": 42, "alias_value": "Abrielle Joseph"}]
}
```

- **segment_additions:** existing store persons who are alumni per the roster;
  add them to the alumni segment and seed the outreach overlay without
  overwriting anything already there.
- **new_members:** create a person entity, anchor it with a ``<source>``
  external ref (the idempotency key), add it to the alumni segment, seed an
  outreach row (``verification`` from the config).
- **staff_members:** create a person entity and add it to the separate staff
  segment (not alumni).
- **name_aliases:** record an alternate spelling on an existing entity.

Idempotent. Usage:

    uv run python -m reconcile_core.profile.drumline.idl_roster \
        [--config-dir DIR] [--db PATH]
"""

from __future__ import annotations

import argparse
import re

from ...store import store
from . import config as config_mod

DEFAULT_SOURCE = "idl-roster"
DEFAULT_ALUMNI_SEGMENT = "illini-drumline-alumni"
DEFAULT_STAFF_SEGMENT = "idl-staff"
DEFAULT_VERIFICATION = "Roster-derived"
REVIEW_STATUS = "Confirmed via IDL roster"
STAFF_SEGMENT_DESCRIPTION = "IDL instructional staff (non-marching)"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _seed_outreach(conn, entity_id: int, verification: str) -> None:
    has_email = (
        "Yes"
        if conn.execute(
            "SELECT 1 FROM contact_points WHERE entity_id=? AND kind='email' LIMIT 1",
            (entity_id,),
        ).fetchone()
        else "No"
    )
    has_phone = (
        "Yes"
        if conn.execute(
            "SELECT 1 FROM contact_points WHERE entity_id=? AND kind='phone' LIMIT 1",
            (entity_id,),
        ).fetchone()
        else "No"
    )
    conn.execute(
        "INSERT OR IGNORE INTO drumline_outreach"
        " (entity_id, verification, has_email, has_phone, review_status)"
        " VALUES (?, ?, ?, ?, ?)",
        (entity_id, verification, has_email, has_phone, REVIEW_STATUS),
    )


def _apply_segment_additions(conn, entries, segment_id: int, verification: str) -> int:
    applied = 0
    for entry in entries:
        entity_id = entry.get("entity_id")
        if entity_id is None:
            continue
        if (
            conn.execute("SELECT 1 FROM entities WHERE id=?", (entity_id,)).fetchone()
            is None
        ):
            continue
        store.add_segment_member(conn, segment_id, entity_id)
        _seed_outreach(conn, entity_id, verification)
        applied += 1
    return applied


def _apply_new_members(
    conn, entries, segment_id: int, source: str, verification: str
) -> int:
    created = 0
    for entry in entries:
        display = entry.get("display_name") or " ".join(
            part for part in (entry.get("first_name"), entry.get("last_name")) if part
        )
        ref = _slug(display)
        if not ref or store.get_entity_by_ref(conn, source, ref) is not None:
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
        _seed_outreach(conn, entity_id, verification)
        created += 1
    return created


def _apply_staff_members(conn, entries, segment_id: int, source: str) -> int:
    created = 0
    for entry in entries:
        display = entry.get("display_name") or " ".join(
            part for part in (entry.get("first_name"), entry.get("last_name")) if part
        )
        ref = _slug(display)
        if not ref or store.get_entity_by_ref(conn, source, ref) is not None:
            continue
        entity_id = store.create_entity(
            conn,
            type="person",
            display_name=display,
            first_name=entry.get("first_name", ""),
            middle_name=entry.get("middle_name", ""),
            last_name=entry.get("last_name", ""),
            notes=entry.get("notes", ""),
        )
        store.add_external_ref(conn, entity_id, source, ref)
        store.add_segment_member(conn, segment_id, entity_id)
        created += 1
    return created


def _apply_aliases(conn, entries, source: str) -> int:
    added = 0
    for entry in entries:
        entity_id = entry.get("entity_id")
        value = entry.get("alias_value")
        if entity_id is None or not value:
            continue
        store.add_alias(conn, entity_id, "aka", value, source=source)
        added += 1
    return added


def apply_idl_roster(db_path=None, config=None) -> dict:
    data = config_mod.idl_roster(config) or {}
    source = data.get("source") or DEFAULT_SOURCE
    verification = data.get("verification") or DEFAULT_VERIFICATION
    conn = store.connect(db_path)
    try:
        with conn:
            alumni_id = store.ensure_segment(
                conn, data.get("alumni_segment") or DEFAULT_ALUMNI_SEGMENT
            )
            staff_id = store.ensure_segment(
                conn,
                data.get("staff_segment") or DEFAULT_STAFF_SEGMENT,
                description=STAFF_SEGMENT_DESCRIPTION,
            )
            additions = _apply_segment_additions(
                conn, data.get("segment_additions") or [], alumni_id, verification
            )
            created = _apply_new_members(
                conn, data.get("new_members") or [], alumni_id, source, verification
            )
            staff = _apply_staff_members(
                conn, data.get("staff_members") or [], staff_id, source
            )
            aliases = _apply_aliases(conn, data.get("name_aliases") or [], source)
    finally:
        conn.close()
    return {
        "segment_additions_applied": additions,
        "new_members_created": created,
        "staff_members_created": staff,
        "aliases_added": aliases,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply the IDL roster membership config"
    )
    parser.add_argument("--config-dir")
    parser.add_argument("--db")
    args = parser.parse_args(argv)

    result = apply_idl_roster(db_path=args.db, config=args.config_dir)
    print("IDL roster applied")
    print(f"  segment additions:   {result['segment_additions_applied']}")
    print(f"  new members:         {result['new_members_created']}")
    print(f"  staff members:       {result['staff_members_created']}")
    print(f"  aliases:             {result['aliases_added']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
