"""Tests for the audition-document affiliations walker (synthetic, no PII)."""

import pytest

from reconcile_core.profile.drumline.audition_affiliations import (
    PLATFORM,
    SOURCE_NAME,
    backfill,
    parse_document,
)
from reconcile_core.profile.drumline.migrate import apply_profile_migrations
from reconcile_core.profile.drumline.sources import register_source
from reconcile_core.store import (
    add_external_ref,
    add_segment_member,
    connect,
    create_entity,
    ensure_segment,
)
from reconcile_core.store.migrate import apply_migrations

ALUMNI = "illini-drumline-alumni"
STAFF = "idl-staff"

MINI = "\n".join(
    [
        "# synthetic extract (same shape as source/audition-2025-results.txt)",
        "p1:1\tSnare:",
        "p1:2\tTina Tester",
        "p1:3\tGhost Person",
        "p1:4\tBass:",
        "p1:5\t0 - Coach Person",
        "p1:6\tKicker - Tina Tester",
        "p1:7\tUndergraduate Staff",
        "p1:8\tCoach Person",
        "p1:9\tIf you accept this invitation, please send an email to",
        "p1:10\tHarding Band Building 1103 S 6th Street Champaign, IL 61820",
    ]
) + "\n"


@pytest.fixture
def env(tmp_path):
    """A store with a name-tier member, a ref-matched staff person, and a source row."""
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    apply_profile_migrations(db)
    conn = connect(db)
    alumni = ensure_segment(conn, ALUMNI)
    staff = ensure_segment(conn, STAFF)

    tina = create_entity(
        conn, type="person", display_name="Tina Tester",
        first_name="Tina", last_name="Tester",
    )
    add_segment_member(conn, alumni, tina)

    coach = create_entity(
        conn, type="person", display_name="Coach Person",
        first_name="Coach", last_name="Person",
    )
    add_external_ref(conn, coach, "idl-roster", "coach-person")
    add_segment_member(conn, staff, coach)

    register_source(conn, name=SOURCE_NAME, kind="audition-results",
                    url="https://example.invalid/results", fetched_at="2026-09-23")
    conn.commit()
    conn.close()

    text = tmp_path / "audition-2025-results.txt"
    text.write_text(MINI, encoding="utf-8")
    return db, text


def test_parse_document_maps_sections_slots_and_stops_at_prose():
    records = parse_document(MINI)
    assert len(records) == 5
    assert [r["ref"] for r in records] == ["p1:2", "p1:3", "p1:5", "p1:6", "p1:8"]
    assert "Harding" not in " ".join(r["name"] for r in records)

    by_ref = {r["ref"]: r for r in records}
    assert (by_ref["p1:2"]["section"], by_ref["p1:2"]["role"]) == ("snares", "member")
    assert (by_ref["p1:5"]["section"], by_ref["p1:5"]["slot"]) == ("basses", 0)
    # Kicker is the seventh bass drum: a named slot inside basses, never a section.
    assert (by_ref["p1:6"]["slot"], by_ref["p1:6"]["slot_label"]) == (None, "Kicker")
    assert by_ref["p1:6"]["section"] == "basses"
    # Staff is a role, not a section.
    assert (by_ref["p1:8"]["role"], by_ref["p1:8"]["section"]) == ("staff", None)


def test_backfill_writes_cell_exact_affiliations_and_is_idempotent(env):
    db, text = env
    result = backfill(db_path=db, text=text)

    assert result["lines"] == 5
    assert result["matched"] == 4
    assert result["unresolved"] == 1
    assert result["affiliations"] == 4
    assert result["duplicate"] == 0
    # The invariant: every person line lands somewhere.
    assert result["resolved_lines"] == result["lines"]

    conn = connect(db)
    try:
        rows = [
            tuple(row)
            for row in conn.execute(
                "SELECT e.display_name, a.role_key, a.season_year, a.section_key,"
                " a.slot, a.slot_label, a.source_ref, a.review_status"
                " FROM affiliations a JOIN entities e ON e.id = a.entity_id"
                " ORDER BY a.source_ref"
            )
        ]
        assert rows == [
            ("Tina Tester", "member", 2025, "snares", None, "", "p1:2",
             "Confirmed via audition results"),
            ("Coach Person", "member", 2025, "basses", 0, "", "p1:5",
             "Confirmed via audition results"),
            ("Tina Tester", "member", 2025, "basses", None, "Kicker", "p1:6",
             "Confirmed via audition results"),
            ("Coach Person", "staff", 2025, None, None, "", "p1:8",
             "Confirmed via audition results"),
        ]
        queued = [
            tuple(row)
            for row in conn.execute(
                "SELECT source_id, display_name FROM unresolved_identities"
                " WHERE platform = ?", (PLATFORM,)
            )
        ]
        assert queued == [("p1:3", "Ghost Person")]
    finally:
        conn.close()

    again = backfill(db_path=db, text=text)
    assert again["affiliations"] == 0
    assert again["duplicate"] == 4
    assert again["resolved_lines"] == again["lines"]


def test_create_missing_makes_a_confirmed_member(env):
    db, text = env
    result = backfill(db_path=db, text=text, create_missing=True)

    assert result["created"] == 1
    conn = connect(db)
    try:
        row = conn.execute(
            "SELECT id FROM entities WHERE display_name = 'Ghost Person'"
        ).fetchone()
        assert row is not None
        entity_id = row["id"]
        segment = conn.execute(
            "SELECT 1 FROM segment_members m JOIN segments s ON s.id = m.segment_id"
            " WHERE m.entity_id = ? AND s.name = ?", (entity_id, ALUMNI)
        ).fetchone()
        assert segment is not None
        affiliation = conn.execute(
            "SELECT season_year, section_key FROM affiliations WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        assert (affiliation["season_year"], affiliation["section_key"]) == (2025, "snares")
        anchor = conn.execute(
            "SELECT 1 FROM external_refs WHERE entity_id = ? AND source = 'audition-2025'",
            (entity_id,),
        ).fetchone()
        assert anchor is not None
    finally:
        conn.close()

    again = backfill(db_path=db, text=text, create_missing=True)
    assert again["created"] == 0
