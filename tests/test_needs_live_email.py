"""Tests for the needs-live-email derivation (synthetic, no PII)."""

import csv

import pytest

from reconcile_core.profile.drumline.needs_live_email import (
    HEADER,
    build_rows,
    derive_needs_live_email,
)
from reconcile_core.store import (
    add_contact_point,
    add_external_ref,
    add_segment_member,
    apply_migrations,
    connect,
    create_entity,
    ensure_segment,
)

SEGMENT = "illini-drumline-alumni"


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    connection = connect(db)
    yield connection
    connection.close()


def _member(conn, segment_id, display_name, emails, *, tracker=None, person=None):
    entity_id = create_entity(conn, type="person", display_name=display_name)
    for address, status in emails:
        add_contact_point(conn, entity_id, "email", address, source="test")
        if status:
            conn.execute(
                "INSERT INTO external_status (entity_id, channel, address, status, observed_at)"
                " VALUES (?, 'email', ?, ?, '2026-01-01')",
                (entity_id, address, status),
            )
    if tracker:
        add_external_ref(conn, entity_id, "tracker_id", tracker)
    if person:
        add_external_ref(conn, entity_id, "master_person_id", person)
    add_segment_member(conn, segment_id, entity_id)
    return entity_id


def test_build_rows_selects_unreachable_members(conn):
    segment_id = ensure_segment(conn, SEGMENT)

    _member(conn, segment_id, "Reachable Person", [("live@example.com", "")])
    _member(
        conn,
        segment_id,
        "Mixed Person",
        [("pending@example.com", "invited"), ("live2@example.com", "")],
    )
    _member(conn, segment_id, "No Email", [], tracker="6001", person="P6001")
    bounced = _member(
        conn, segment_id, "Bounced Only", [("gone@example.com", "bouncing")]
    )
    invited = _member(
        conn, segment_id, "Invited Only", [("pending2@example.com", "invited")]
    )

    rows = build_rows(conn)
    by_id = {row["Person_ID"]: row for row in rows}

    assert len(rows) == 3
    assert "Reachable Person" not in {row["Person"] for row in rows}
    assert "Mixed Person" not in {row["Person"] for row in rows}

    assert by_id["P6001"]["Notes"] == "No email on file"
    assert by_id["P6001"]["Tracker_IDs"] == "6001"
    assert by_id[f"P9{bounced}"]["Flagged_Addresses"] == "gone@example.com"
    assert "bouncing" in by_id[f"P9{bounced}"]["Notes"]
    assert by_id[f"P9{invited}"]["Known_Addresses"] == "pending2@example.com"


def test_derive_writes_csv(conn, tmp_path):
    # derive_* opens its own connection, so build the store via a file path
    db = tmp_path / "store.db"
    apply_migrations(db)
    other = connect(db)
    segment_id = ensure_segment(other, SEGMENT)
    _member(other, segment_id, "No Email", [], tracker="7001", person="P7001")
    other.commit()
    other.close()

    out = tmp_path / "backlog.csv"
    count = derive_needs_live_email(out, db_path=db)

    assert count == 1
    with open(out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0].keys()) == HEADER
    assert rows[0]["Person"] == "No Email"
    assert rows[0]["Person_ID"] == "P7001"
