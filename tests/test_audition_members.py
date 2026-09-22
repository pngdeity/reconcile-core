"""Tests for the audition-members importer (synthetic, no PII)."""

import json

import pytest

from reconcile_core.profile.drumline.audition_members import apply_audition_members
from reconcile_core.profile.drumline.migrate import apply_profile_migrations
from reconcile_core.store import apply_migrations, connect
from reconcile_core.store import store as store_mod

SEGMENT = "illini-drumline-alumni"


def _write_config(directory, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "audition_members.json").write_text(json.dumps(payload))
    return directory


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    apply_profile_migrations(db)

    conn = connect(db)
    try:
        entity_id = store_mod.create_entity(conn, type="person")  # nameless
        store_mod.add_contact_point(
            conn, entity_id, "email", "aaron.colon2024@example.com"
        )
        segment = store_mod.ensure_segment(conn, SEGMENT)
        store_mod.add_segment_member(conn, segment, entity_id)
        conn.commit()
    finally:
        conn.close()

    config = _write_config(
        tmp_path / "cfg",
        {
            "source": "audition-test",
            "name_fills": [
                {
                    "entity_id": entity_id,
                    "email": "aaron.colon2024@example.com",
                    "first_name": "Aaron",
                    "last_name": "Colon",
                    "display_name": "Aaron Colon",
                }
            ],
            "new_members": [
                {
                    "first_name": "New",
                    "last_name": "Member",
                    "display_name": "New Member",
                }
            ],
        },
    )
    return db, config, entity_id


def _count(db, sql):
    conn = connect(db)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_name_fill_and_new_member(env):
    db, config, entity_id = env
    result = apply_audition_members(db_path=db, config=config)

    assert result["name_fills_applied"] == 1
    assert result["new_members_created"] == 1
    assert result["conflicts"] == []

    conn = connect(db)
    try:
        row = conn.execute(
            "SELECT display_name, first_name, last_name FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        assert row["display_name"] == "Aaron Colon"
        assert row["first_name"] == "Aaron"
        assert row["last_name"] == "Colon"
    finally:
        conn.close()

    assert _count(db, "SELECT COUNT(*) FROM segment_members") == 2
    assert (
        _count(
            db,
            "SELECT COUNT(*) FROM drumline_outreach WHERE review_status = 'Confirmed via audition results'",
        )
        == 1
    )


def test_idempotent(env):
    db, config, _ = env
    apply_audition_members(db_path=db, config=config)
    second = apply_audition_members(db_path=db, config=config)

    assert second["name_fills_applied"] == 0
    assert second["new_members_created"] == 0
    assert second["conflicts"] == []
    assert _count(db, "SELECT COUNT(*) FROM entities") == 2
    assert _count(db, "SELECT COUNT(*) FROM segment_members") == 2


def test_conflicting_name_is_reported(env):
    db, config, entity_id = env
    conn = connect(db)
    try:
        conn.execute(
            "UPDATE entities SET first_name = 'Different' WHERE id = ?", (entity_id,)
        )
        conn.commit()
    finally:
        conn.close()

    result = apply_audition_members(db_path=db, config=config)

    assert any("first_name" in conflict for conflict in result["conflicts"])
    assert (
        _count(db, "SELECT COUNT(*) FROM entities WHERE first_name = 'Different'") == 1
    )


def test_external_ref_is_idempotency_key(env):
    db, config, _ = env
    apply_audition_members(db_path=db, config=config)
    assert (
        _count(
            db,
            "SELECT COUNT(*) FROM external_refs WHERE source = 'audition-test'",
        )
        == 1
    )
