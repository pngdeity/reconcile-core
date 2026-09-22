"""Round-trip parity for the Google Contacts CSV projection.

Import a synthetic Contacts.csv (no PII) into a fresh store, export it again,
and require every cell to match. This is the B2 migration gate: the Google
Contacts projection must reproduce what it consumed.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from reconcile_core.io import google_csv
from reconcile_core.store.migrate import apply_migrations


def _row(**values: str) -> dict:
    row = {c: "" for c in google_csv.HEADER}
    row.update(values)
    return row


def _sample_rows() -> list[dict]:
    return [
        _row(
            ID="1",
            **{
                "First Name": "Ada",
                "Middle Name": "M",
                "Last Name": "Lovelace",
                "Nickname": "Ada",
                "Notes": "note, with comma",
                "E-mail 1 - Label": "Home",
                "E-mail 1 - Value": "ada@example.com",
                "E-mail 2 - Label": "Work",
                "E-mail 2 - Value": "ada@corp.example.com",
                "E-mail 3 - Label": "School",  # label-only slot
                "Phone 1 - Label": "Mobile",
                "Phone 1 - Value": "+15551234567",
                "Address 1 - Label": "Home",
                "Address 1 - Formatted": "1 Analytical Way, London, ON N1, Canada",
                "Address 1 - Street": "1 Analytical Way",
                "Address 1 - City": "London",
                "Address 1 - Region": "ON",
                "Address 1 - Postal Code": "N1",
                "Address 1 - Country": "Canada",
                "Website 1 - Label": "LinkedIn",
                "Website 1 - Value": "https://linkedin.com/in/ada",
                "Photo": "https://example.com/ada.jpg",
                "Relation 1 - Label": "Spouse",
                "Relation 1 - Value": "Charles",
                "Phonetic First Name": "Ayda",
                "Custom Field 1 - Label": "Alumni Status",
                "Custom Field 1 - Value": "Illini Drumline",
                "Custom Field 2 - Label": "GitHub",
                "Custom Field 2 - Value": "adal",
                "Custom Field 3 - Label": "Pronouns",
            },
        ),
        _row(
            ID="2",
            **{
                "First Name": "Grace",
                "Last Name": "Hopper",
                "Custom Field 1 - Label": "Name pronunciation",
                "Custom Field 1 - Value": "REE-ann",
                # structured-only address (no Formatted)
                "Address 1 - Street": "2 Compiler Ct",
                "Address 1 - City": "Arlington",
                # an empty value with a label
                "Phone 2 - Label": "Home",
                "Website 2 - Label": "Profile",
            },
        ),
        _row(
            ID="3",
            **{
                "Organization Name": "Example Org",
                "Organization Title": "Support",
                "E-mail 1 - Label": "Work",
                "E-mail 1 - Value": "support@example.org",
            },
        ),
        _row(
            ID="4",
            **{
                "First Name": "Cora",
                "Last Name": "Bell",
                "Custom Field 1 - Label": "Alumni Status",
                "Custom Field 1 - Value": "Illini Drumline",
                "Custom Field 2 - Label": "Matrix",
                "Custom Field 2 - Value": "@cora:example.org",
            },
        ),
    ]


def _write_sample(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=google_csv.HEADER, quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        writer.writerows(rows)


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture()
def round_trip(tmp_path):
    sample = tmp_path / "Contacts.csv"
    rows = _sample_rows()
    _write_sample(sample, rows)

    db = tmp_path / "store" / "contacts.db"
    out = tmp_path / "out"
    stats = google_csv.import_contacts(sample, db)
    google_csv.export_contacts(out, db)
    return rows, stats, db, out


def test_round_trip_every_cell_matches(round_trip):
    rows, _stats, _db, out = round_trip
    exported = {r["ID"]: r for r in _read(out / "Contacts.csv")}
    assert set(exported) == {r["ID"] for r in rows}
    for original in rows:
        got = exported[original["ID"]]
        for column in google_csv.HEADER:
            assert got[column] == original[column], (
                f"ID {original['ID']} column {column!r}: "
                f"{got[column]!r} != {original[column]!r}"
            )


def test_import_counts(round_trip):
    rows, stats, _db, _out = round_trip
    assert stats["created"] == len(rows)
    assert stats["skipped"] == 0
    assert stats["alumni"] == 2
    assert stats["counts"]["entities"] == len(rows)


def test_import_is_idempotent(round_trip):
    rows, _stats, db, _out = round_trip
    again = google_csv.import_contacts(db.parent.parent / "Contacts.csv", db)
    assert again["created"] == 0
    assert again["skipped"] == len(rows)


def test_import_file_shape(round_trip):
    _rows, _stats, _db, out = round_trip
    with open(out / "Contacts_import.csv", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == google_csv.IMPORT_HEADER
    assert "ID" not in header
    assert len(header) == 61


def test_marker_membership(round_trip):
    _rows, _stats, db, _out = round_trip
    import sqlite3

    conn = sqlite3.connect(db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM segment_members sm JOIN segments s "
            "ON s.id = sm.segment_id WHERE s.name = ?",
            (google_csv.MARKER_SEGMENT,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 2


def test_export_only_google_entities(tmp_path):
    db = tmp_path / "s.db"
    apply_migrations(db)
    from reconcile_core.store import store as store_mod

    conn = store_mod.connect(db)
    try:
        store_mod.create_entity(conn, first_name="No", last_name="Ref")
        conn.commit()
    finally:
        conn.close()
    out = tmp_path / "out"
    stats = google_csv.export_contacts(out, db)
    assert stats["rows"] == 0
    assert _read(out / "Contacts.csv") == []
