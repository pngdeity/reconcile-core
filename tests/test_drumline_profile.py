"""Tests for the drumline profile (B5). Synthetic, no PII."""

import csv
import json
from pathlib import Path

import pytest

from reconcile_core.profile.drumline.config import config_dir
from reconcile_core.profile.drumline.export_members import export_members
from reconcile_core.profile.drumline.import_drumline import run as import_drumline
from reconcile_core.profile.drumline.import_master import seed_outreach
from reconcile_core.profile.drumline.migrate import apply_profile_migrations
from reconcile_core.profile.drumline.name_resolutions import apply_resolutions
from reconcile_core.store import store

TRACKER_HEADER = [
    "ID",
    "First Name",
    "Middle",
    "Last Name",
    "Email",
    "Contacts ID",
    "Facebook Profile Link",
    "Notes",
    "Verification",
]

MASTER_HEADER = [
    "Person_ID",
    "First_Name",
    "Last_Name",
    "Display_Name",
    "Email_Primary",
    "Email_All",
    "Phone",
    "Verification",
    "Tracker_IDs",
    "Contacts_IDs",
    "Dumps_Seen",
    "Reached_Dumps_1_6",
    "Reached_Dump_0",
    "Has_Email",
    "Has_Phone",
    "Tracker_Notes",
    "Needs_First_Outreach",
    "Review_Status",
]


def write_csv(path: Path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def make_config(tmp_path: Path, **files) -> Path:
    directory = tmp_path / "config"
    directory.mkdir(exist_ok=True)
    for name, payload in files.items():
        (directory / f"{name}.json").write_text(json.dumps(payload))
    return directory


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "contacts.db"
    assert apply_profile_migrations(path) == 2
    return path


def test_profile_migration_creates_overlay(db):
    conn = store.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "drumline_outreach" in tables
        assert store.counts(conn)["entities"] == 0
    finally:
        conn.close()


def test_import_drumline_segment_and_decision_state(tmp_path, db):
    tracker = tmp_path / "Tracker.csv"
    write_csv(
        tracker,
        TRACKER_HEADER,
        [
            {
                "ID": "5001",
                "First Name": "Jane",
                "Middle": "",
                "Last Name": "Doe",
                "Email": "jane@example.com",
                "Contacts ID": "101",
                "Facebook Profile Link": "",
                "Notes": "note",
                "Verification": "Verified",
            }
        ],
    )
    config = make_config(
        tmp_path,
        manual_address_map={
            "extra@example.com": {
                "person": "Jane Doe",
                "tracker_id": "5001",
                "note": "x",
            }
        },
        group_invite_required={"invite_required": []},
        group_blocked={"blocked": []},
        group_hold={"hold": []},
    )

    stats = import_drumline(tracker, db_path=db, config=config)
    assert stats["created"] == 1
    assert stats["segment_members"] == 1
    assert stats["decision_added"] == 1

    conn = store.connect(db)
    try:
        entity_id = store.get_entity_by_ref(conn, "tracker_id", "5001")
        assert entity_id is not None
        emails = {
            row["value"]
            for row in conn.execute(
                "SELECT value FROM contact_points WHERE entity_id=? AND kind='email'",
                (entity_id,),
            )
        }
        assert emails == {"extra@example.com"}
        aliases = {
            (row["alias_type"], row["alias_value"])
            for row in conn.execute(
                "SELECT alias_type, alias_value FROM aliases WHERE entity_id=?",
                (entity_id,),
            )
        }
        assert ("tracker_verification", "Verified") in aliases
        assert ("tracker_notes", "note") in aliases
    finally:
        conn.close()

    again = import_drumline(tracker, db_path=db, config=config)
    assert again["decision_added"] == 0
    assert again["created"] == 0


def test_seed_outreach_and_name_resolutions_and_export(tmp_path, db):
    tracker = tmp_path / "Tracker.csv"
    write_csv(
        tracker,
        TRACKER_HEADER,
        [
            {
                "ID": "5001",
                "First Name": "Jane",
                "Middle": "",
                "Last Name": "Doe",
                "Email": "jane@example.com",
                "Contacts ID": "101",
                "Facebook Profile Link": "",
                "Notes": "",
                "Verification": "Email-derived",
            }
        ],
    )
    import_drumline(tracker, db_path=db, config=make_config(tmp_path))

    master = tmp_path / "master.csv"
    write_csv(
        master,
        MASTER_HEADER,
        [
            {
                "Person_ID": "P0001",
                "First_Name": "Jane",
                "Last_Name": "Doe",
                "Display_Name": "Jane Doe",
                "Email_Primary": "jane@example.com",
                "Email_All": "jane@example.com",
                "Phone": "",
                "Verification": "Email-derived",
                "Tracker_IDs": "5001",
                "Contacts_IDs": "101",
                "Dumps_Seen": "0,1",
                "Reached_Dumps_1_6": "yes",
                "Reached_Dump_0": "yes",
                "Has_Email": "Yes",
                "Has_Phone": "No",
                "Tracker_Notes": "",
                "Needs_First_Outreach": "No",
                "Review_Status": "",
            }
        ],
    )
    seeded = seed_outreach(master, db_path=db)
    assert seeded["linked"] == 1
    assert seeded["unresolved"] == []

    config = make_config(
        tmp_path,
        manual_name_resolutions={
            "resolutions": [
                {
                    "person": "P0001",
                    "match": {"source": "tracker_id", "ref_value": "5001"},
                    "set": {"last_name": "Zed", "display_name": "Jane Zed"},
                    "aliases": [{"alias_type": "aka", "alias_value": "Jane Doe"}],
                    "outreach": {"verification": "Verified"},
                }
            ]
        },
    )
    result = apply_resolutions(db_path=db, config=config)
    assert result["applied"] == 1

    out = tmp_path / "drumline-members.csv"
    count = export_members(out, db_path=db)
    assert count == 1
    row = next(csv.DictReader(open(out, newline="", encoding="utf-8")))
    assert row["Person_ID"] == "P0001"
    assert row["Last_Name"] == "Zed"
    assert row["Display_Name"] == "Jane Zed"
    assert row["Verification"] == "Verified"
    assert row["Tracker_IDs"] == "5001"
    assert row["Contacts_IDs"] == ""
    assert row["Email_Primary"] == ""
    assert row["Dumps_Seen"] == "0,1"


def test_entity_merge(tmp_path, db):
    conn = store.connect(db)
    try:
        keep = store.create_entity(conn, type="person", display_name="Rachel")
        store.add_external_ref(conn, keep, "google_contacts_id", "1728")
        drop = store.create_entity(conn, type="person", display_name="")
        store.add_external_ref(conn, drop, "google_contacts_id", "1120")
        store.add_contact_point(conn, drop, "email", "misurac@example.com")
        conn.commit()
    finally:
        conn.close()

    tracker = tmp_path / "Tracker.csv"
    write_csv(tracker, TRACKER_HEADER, [])
    config = make_config(
        tmp_path,
        manual_entity_merges={"merges": [{"keep_gcid": "1728", "merge_gcid": "1120"}]},
    )

    stats = import_drumline(tracker, db_path=db, config=config)
    assert stats["merges_applied"] == 1

    conn = store.connect(db)
    try:
        assert store.get_entity_by_ref(conn, "google_contacts_id", "1120") is None
        emails = [
            row["value"]
            for row in conn.execute(
                "SELECT value FROM contact_points WHERE entity_id=? AND kind='email'",
                (keep,),
            )
        ]
        assert emails == ["misurac@example.com"]
    finally:
        conn.close()


def test_config_dir_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("RECONCILE_CORE_DRUMLINE_CONFIG", str(tmp_path / "envcfg"))
    assert config_dir() == tmp_path / "envcfg"
    assert config_dir(tmp_path / "explicit") == tmp_path / "explicit"
