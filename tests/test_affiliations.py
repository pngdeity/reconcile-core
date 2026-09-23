"""Tests for the roster-grid affiliations backfill (synthetic, no PII)."""

import csv

import pytest

from reconcile_core.profile.drumline.affiliations import (
    BANDS,
    backfill,
    parse_cell,
    retire_notes,
)
from reconcile_core.profile.drumline.migrate import apply_profile_migrations
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


def _annotation(raw, kind):
    return next(a for a in parse_cell(raw)["annotations"] if a["kind"] == kind)


def test_parse_cell_reads_each_annotation_semantic():
    nick = _annotation("Steve Theis (Zoidberg)", "nickname")
    assert (nick["value"], nick["confidence"]) == ("Zoidberg", "likely")
    assert parse_cell("Steve Theis (Zoidberg)")["name"] == "Steve Theis"

    maiden = _annotation("Stacy (Zaun) Eifert", "maiden_name")
    assert maiden["value"] == "Zaun"

    assert _annotation("Karen (Max) Parkinson", "review")["value"] == "Max"
    assert _annotation("Michael Boykins (timbali)", "review")["value"] == "timbali"

    uncertain = _annotation("Dean Wade (Bucky)?", "nickname")
    assert (uncertain["value"], uncertain["confidence"]) == ("Bucky", "uncertain")

    unit = _annotation("Graham Stapleton B-Line", "unit")
    assert unit["value"].lower() == "b-line"

    hedge = _annotation("Wally Jobush, maybe Jobusch", "name")
    assert hedge["confidence"] == "uncertain"
    assert parse_cell("Wally Jobush, maybe Jobusch")["name"] == "Wally Jobush"


def test_parse_cell_normalizes_names():
    assert parse_cell("Walter, Rick")["name"] == "Rick Walter"
    assert parse_cell("Grace O\u2019Brien *")["name"] == "Grace O\u2019Brien"
    assert parse_cell("Anna Boone ")["name"] == "Anna Boone"
    assert parse_cell("p. dicky")["name"] == "p. dicky"


GRID = [
    ["2023", "2022"],
    ["Snare:", "Snare:"],
    ["Tina Tester", "Tina Tester"],
    ["Steve Theis (Zoidberg)", ""],
    ["Staff:", "Staff:"],
    ["Coach Person", "Coach Person"],
    ["Ghost Person", ""],
    ["April _____", ""],
]


@pytest.fixture
def env(tmp_path):
    """A store with a ref-matched member, a staff person and a name-tier match."""
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    apply_profile_migrations(db)
    conn = connect(db)
    alumni = ensure_segment(conn, ALUMNI)
    staff = ensure_segment(conn, STAFF)

    steve = create_entity(
        conn, type="person", display_name="Steve Theis",
        first_name="Steve", last_name="Theis",
    )
    add_external_ref(conn, steve, "idl-roster", "steve-theis-zoidberg")
    add_segment_member(conn, alumni, steve)

    coach = create_entity(
        conn, type="person", display_name="Coach Person",
        first_name="Coach", last_name="Person",
    )
    add_external_ref(conn, coach, "idl-roster", "coach-person")
    add_segment_member(conn, staff, coach)

    tina = create_entity(
        conn, type="person", display_name="Tina Tester",
        first_name="Tina", last_name="Tester",
    )
    add_segment_member(conn, alumni, tina)
    conn.commit()
    conn.close()

    grid = tmp_path / "idl-roster-beatrack.csv"
    with grid.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(GRID)
    return db, grid


def test_backfill_records_cell_exact_affiliations(env):
    db, grid = env
    result = backfill(db_path=db, grid=grid)
    conn = connect(db)
    rows = [
        tuple(row)
        for row in conn.execute(
            "SELECT role_key, season_year, section_key, slot, source_ref, raw_text"
            " FROM affiliations ORDER BY season_year DESC, slot"
        )
    ]
    assert len(rows) == 5
    assert ("member", 2023, "snares", 1, "r2:c0", "Tina Tester") in rows
    assert ("member", 2023, "snares", 2, "r3:c0", "Steve Theis (Zoidberg)") in rows
    assert ("member", 2022, "snares", 1, "r2:c1", "Tina Tester") in rows
    assert ("staff", 2023, None, 1, "r5:c0", "Coach Person") in rows
    assert ("staff", 2022, None, 1, "r5:c1", "Coach Person") in rows

    # A nickname is a sourced claim, not prose.
    claims = [
        tuple(row)
        for row in conn.execute(
            "SELECT alias_type, alias_value, confidence, source_ref FROM aliases"
            " WHERE alias_type='nickname'"
        )
    ]
    assert claims == [("nickname", "Zoidberg", "likely", "r3:c0")]

    # Nothing is dropped: every cell (labels are not cells) is an affiliation
    # or an unresolved row.
    unresolved = conn.execute(
        "SELECT count(*) FROM unresolved_identities"
    ).fetchone()[0]
    cells = sum(
        1 for row in GRID[1:] for cell in row if cell and cell.lower() not in BANDS
    )
    assert cells == len(rows) + unresolved
    assert unresolved == 2
    conn.close()
    assert result["stats"]["affiliations"] == 5


def test_backfill_is_idempotent(env):
    db, grid = env
    backfill(db_path=db, grid=grid)
    backfill(db_path=db, grid=grid)
    conn = connect(db)
    assert conn.execute("SELECT count(*) FROM affiliations").fetchone()[0] == 5
    assert conn.execute("SELECT count(*) FROM aliases").fetchone()[0] == 1
    assert (
        conn.execute("SELECT count(*) FROM unresolved_identities").fetchone()[0] == 2
    )
    conn.close()


def test_retire_notes_verifies_before_stripping(env):
    """Prose is retired only where the store's affiliations match it."""
    db, grid = env
    backfill(db_path=db, grid=grid)
    conn = connect(db)
    tina = conn.execute(
        "SELECT id FROM entities WHERE display_name='Tina Tester'"
    ).fetchone()[0]
    steve = conn.execute(
        "SELECT id FROM entities WHERE display_name='Steve Theis'"
    ).fetchone()[0]
    # two appended roster segments, both matching the store
    conn.execute(
        "UPDATE entities SET notes=? WHERE id=?",
        ("IDL roster: Snare; 2022-2022; IDL roster: Snare; 2023-2023", tina),
    )
    # a note claiming seasons the store does not have
    conn.execute(
        "UPDATE entities SET notes=? WHERE id=?",
        ("IDL roster: Snare; 2019-2023", steve),
    )
    conn.commit()
    conn.close()

    result = retire_notes(db_path=db, dry_run=False)
    conn = connect(db)
    assert conn.execute("SELECT notes FROM entities WHERE id=?", (tina,)).fetchone()[0] == ""
    assert "IDL roster" in (
        conn.execute("SELECT notes FROM entities WHERE id=?", (steve,)).fetchone()[0]
    )
    conn.close()
    assert result["stats"]["retired"] == 1
    assert result["stats"]["mismatches"] == 1


def test_rejected_match_is_queued_not_attached(env):
    """The Michael Johnson rule: a rejected roster match stays unresolved."""
    db, grid = env
    conn = connect(db)
    alumni = ensure_segment(conn, ALUMNI)
    mike = create_entity(
        conn, type="person", display_name="Ghost Person",
        first_name="Ghost", last_name="Person",
    )
    add_external_ref(conn, mike, "idl-roster", "ghost-person")
    add_segment_member(conn, alumni, mike)
    conn.execute(
        "INSERT INTO decision_state (entity_id, channel, status, reason, source)"
        " VALUES (?,?,?,?,?)",
        (mike, "idl-roster", "rejected", "false positive (test)", "test"),
    )
    conn.commit()
    conn.close()

    backfill(db_path=db, grid=grid)
    conn = connect(db)
    assert (
        conn.execute(
            "SELECT count(*) FROM affiliations WHERE entity_id=?", (mike,)
        ).fetchone()[0]
        == 0
    )
    queued = conn.execute(
        "SELECT display_name FROM unresolved_identities WHERE platform='idl-roster-cell'"
    ).fetchall()
    assert any("Ghost Person" in row[0] for row in queued)
    conn.close()
