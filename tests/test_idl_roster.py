"""Tests for the IDL historical-roster importer (synthetic, no PII)."""

import json

import pytest

from reconcile_core.profile.drumline.idl_roster import apply_idl_roster
from reconcile_core.profile.drumline.migrate import apply_profile_migrations
from reconcile_core.store import apply_migrations, connect, create_entity

ALUMNI = "illini-drumline-alumni"
STAFF = "idl-staff"


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    apply_profile_migrations(db)
    conn = connect(db)
    existing = create_entity(
        conn,
        type="person",
        display_name="David Schroeder",
        first_name="David",
        last_name="Schroeder",
    )
    conn.commit()
    conn.close()

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "idl_roster.json").write_text(
        json.dumps(
            {
                "source": "idl-roster",
                "verification": "Roster-derived",
                "alumni_segment": ALUMNI,
                "staff_segment": STAFF,
                "segment_additions": [
                    {
                        "entity_id": existing,
                        "matched_name": "David Schroeder",
                        "sections": "Snare",
                        "years": "1970,1971",
                    }
                ],
                "new_members": [
                    {
                        "display_name": "Akira Robles",
                        "first_name": "Akira",
                        "last_name": "Robles",
                        "notes": "IDL roster: Basses/Staff; 2005-2013",
                    }
                ],
                "staff_members": [
                    {
                        "display_name": "Fred Fairchild",
                        "first_name": "Fred",
                        "last_name": "Fairchild",
                        "notes": "IDL roster: Staff; 1974-1976",
                    }
                ],
                "name_aliases": [
                    {"entity_id": existing, "alias_value": "Dave Schroeder"}
                ],
            }
        ),
        encoding="utf-8",
    )
    return db, config_dir, existing


def _segment_entities(conn, name):
    return {
        row["entity_id"]
        for row in conn.execute(
            "SELECT sm.entity_id FROM segment_members sm"
            " JOIN segments s ON s.id = sm.segment_id WHERE s.name = ?",
            (name,),
        )
    }


def test_apply_idl_roster(env):
    db, config_dir, existing = env
    result = apply_idl_roster(db_path=db, config=config_dir)

    assert result == {
        "segment_additions_applied": 1,
        "segment_additions_skipped": 0,
        "new_members_created": 1,
        "staff_members_created": 1,
        "aliases_added": 1,
    }

    conn = connect(db)
    alumni = _segment_entities(conn, ALUMNI)
    staff = _segment_entities(conn, STAFF)

    assert existing in alumni
    assert len(alumni) == 2
    assert len(staff) == 1
    assert staff.isdisjoint(alumni)

    staff_entity = conn.execute(
        "SELECT first_name, notes FROM entities WHERE id = ?", (next(iter(staff)),)
    ).fetchone()
    assert staff_entity["first_name"] == "Fred"
    assert staff_entity["notes"] == "IDL roster: Staff; 1974-1976"

    outreach = conn.execute(
        "SELECT verification, review_status FROM drumline_outreach WHERE entity_id = ?",
        (existing,),
    ).fetchone()
    assert outreach["verification"] == "Roster-derived"
    assert outreach["review_status"] == "Confirmed via IDL roster"

    alias = conn.execute(
        "SELECT alias_type, alias_value FROM aliases WHERE entity_id = ?", (existing,)
    ).fetchone()
    assert (alias["alias_type"], alias["alias_value"]) == ("aka", "Dave Schroeder")

    ref = conn.execute(
        "SELECT source, ref_value FROM external_refs WHERE entity_id != ?", (existing,)
    ).fetchall()
    assert {row["ref_value"] for row in ref} == {"akira-robles", "fred-fairchild"}
    conn.close()


def test_rejected_entity_is_not_added(env):
    """A manual 'rejected' decision must block the segment addition."""
    db, config_dir, existing = env
    conn = connect(db)
    conn.execute(
        "INSERT INTO decision_state (entity_id, channel, status, source, observed_at)"
        " VALUES (?, 'idl-roster', 'rejected', 'manual_review', '2026-09-23')",
        (existing,),
    )
    conn.commit()
    conn.close()

    result = apply_idl_roster(db_path=db, config=config_dir)

    assert result["segment_additions_applied"] == 0
    assert result["segment_additions_skipped"] == 1

    conn = connect(db)
    assert existing not in _segment_entities(conn, ALUMNI)
    conn.close()


def test_apply_is_idempotent(env):
    db, config_dir, _ = env
    apply_idl_roster(db_path=db, config=config_dir)
    second = apply_idl_roster(db_path=db, config=config_dir)

    assert second["new_members_created"] == 0
    assert second["staff_members_created"] == 0

    conn = connect(db)
    assert len(_segment_entities(conn, ALUMNI)) == 2
    assert len(_segment_entities(conn, STAFF)) == 1
    counts = conn.execute(
        "SELECT (SELECT COUNT(*) FROM entities) AS e,"
        " (SELECT COUNT(*) FROM external_refs) AS r"
    ).fetchone()
    assert (counts["e"], counts["r"]) == (3, 2)
    conn.close()
