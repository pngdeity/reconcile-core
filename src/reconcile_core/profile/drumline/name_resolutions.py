"""Apply versioned manual name resolutions to the store.

Ports illini ``working/apply_name_resolutions.py``. Reads the profile config
(default ``var/drumline/manual_name_resolutions.json``) and, per entry:
resolves the entity via ``external_refs``, applies ``set`` overrides, adds
aliases, and syncs the ``tracker_verification`` alias + ``drumline_outreach``
verification. Idempotent.

Usage:
    uv run python -m reconcile_core.profile.drumline.name_resolutions \
        [--config-dir DIR] [--db PATH]
"""

from __future__ import annotations

import argparse

from ...store import store
from . import config as config_mod

ALLOWED_FIELDS = {
    "first_name",
    "middle_name",
    "last_name",
    "nickname",
    "display_name",
    "notes",
    "org_name",
    "title",
    "department",
    "birthday",
}


def resolve_entity(conn, entry):
    if entry.get("entity_id"):
        return entry["entity_id"]
    match = entry.get("match")
    if not match:
        return None
    row = conn.execute(
        "SELECT entity_id FROM external_refs WHERE source = ? AND ref_value = ?",
        (match["source"], match["ref_value"]),
    ).fetchone()
    return row[0] if row else None


def _apply(conn, entries) -> dict:
    applied = 0
    skipped: list[str] = []
    for entry in entries:
        entity_id = resolve_entity(conn, entry)
        if entity_id is None:
            skipped.append(entry.get("person") or entry.get("match"))
            continue

        for field, value in (entry.get("set") or {}).items():
            if field not in ALLOWED_FIELDS:
                raise SystemExit(f"field not allowed: {field}")
            conn.execute(
                f"UPDATE entities SET {field} = ? WHERE id = ?", (value, entity_id)
            )

        for alias in entry.get("aliases") or []:
            conn.execute(
                "INSERT OR IGNORE INTO aliases (entity_id, alias_type, alias_value, source) "
                "VALUES (?, ?, ?, 'manual_name_resolution')",
                (entity_id, alias["alias_type"], alias["alias_value"]),
            )

        outreach = entry.get("outreach") or {}
        if outreach.get("verification"):
            conn.execute(
                "UPDATE drumline_outreach SET verification = ? WHERE entity_id = ?",
                (outreach["verification"], entity_id),
            )
            conn.execute(
                "DELETE FROM aliases WHERE entity_id = ? AND alias_type = 'tracker_verification'",
                (entity_id,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO aliases (entity_id, alias_type, alias_value, source) "
                "VALUES (?, 'tracker_verification', ?, 'manual_name_resolution')",
                (entity_id, outreach["verification"]),
            )

        applied += 1
    return {"applied": applied, "skipped": skipped}


def apply_resolutions(db_path=None, config=None) -> dict:
    conn = store.connect(db_path)
    try:
        result = _apply(conn, config_mod.resolutions(config))
        conn.commit()
        return result
    finally:
        conn.close()


run = apply_resolutions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", default=None, help="drumline config directory")
    parser.add_argument("--db", default=None, help="contacts store path")
    args = parser.parse_args()

    result = apply_resolutions(db_path=args.db, config=args.config_dir)
    print(f"resolutions applied: {result['applied']}")
    if result["skipped"]:
        print(f"skipped (no entity): {result['skipped']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
