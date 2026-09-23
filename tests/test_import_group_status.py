"""Tests for the Google Groups status ingest (synthetic, no PII)."""

import csv

import pytest

from reconcile_core.profile.drumline.import_group_status import (
    import_group_status,
    load_export,
    norm,
)
from reconcile_core.store import (
    add_contact_point,
    apply_migrations,
    connect,
    create_entity,
)

CHANNEL = "google_groups"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "contacts.db"
    apply_migrations(path)
    return path


def _export(directory, rows):
    path = directory / "group-membership.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Members for group Test"])
        writer.writerow(["Email address", "Nickname", "Group status", "Email status"])
        for row in rows:
            writer.writerow(row)
    return path


def test_norm_strips_gmail_dots_only():
    assert norm("John.Doe@Gmail.com") == "johndoe@gmail.com"
    assert norm("John.Doe@Example.com") == "john.doe@example.com"


def test_load_export_skips_title_and_blank_rows(tmp_path):
    path = _export(tmp_path, [["a@example.com", "A", "member", ""], ["", "", "", ""]])
    assert load_export(path) == [("a@example.com", "A", "member", "")]


def test_import_links_entities_and_is_idempotent(db):
    conn = connect(db)
    entity_id = create_entity(conn, display_name="Test Person")
    add_contact_point(conn, entity_id, "email", "Person@Example.com", source="test")
    conn.commit()
    conn.close()

    path = _export(db.parent, [["person@example.com", "Test Person", "member", ""]])
    first = import_group_status(path, db_path=db, observed_at="2026-09-23")
    second = import_group_status(path, db_path=db, observed_at="2026-09-23")

    assert first["rows"] == 1
    assert first["linked"] == 1
    assert second["snapshot"] == 1
    assert second["latest"] == "2026-09-23"

    conn = connect(db)
    rows = conn.execute(
        "SELECT entity_id, address, status, email_status FROM external_status"
        " WHERE channel = ? AND observed_at = ?",
        (CHANNEL, "2026-09-23"),
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["entity_id"] == entity_id
    assert rows[0]["address"] == "person@example.com"
    assert rows[0]["status"] == "member"


def test_import_records_unlinked_addresses(db):
    path = _export(db.parent, [["stranger@example.com", "", "invited", "bouncing"]])
    stats = import_group_status(path, db_path=db, observed_at="2026-09-23")

    assert stats["linked"] == 0
    assert stats["by_status"] == {"invited": 1}

    conn = connect(db)
    row = conn.execute(
        "SELECT entity_id, email_status FROM external_status WHERE address = ?",
        ("stranger@example.com",),
    ).fetchone()
    conn.close()
    assert row["entity_id"] is None
    assert row["email_status"] == "bouncing"
