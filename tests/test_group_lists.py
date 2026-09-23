"""Tests for the Google Groups target/run-list builder (synthetic, no PII)."""

import csv

import pytest

from reconcile_core.profile.drumline import group_lists
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
def store(tmp_path):
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    conn = connect(db)
    segment_id = ensure_segment(conn, SEGMENT)

    def member(name, emails, *, tracker=None):
        entity_id = create_entity(conn, display_name=name)
        for position, address in enumerate(emails, start=1):
            add_contact_point(
                conn, entity_id, "email", address, position=position, source="test"
            )
        if tracker:
            add_external_ref(conn, entity_id, "tracker_id", tracker)
        add_segment_member(conn, segment_id, entity_id)
        return entity_id

    yield {"db": db, "conn": conn, "member": member}
    conn.close()


@pytest.fixture(autouse=True)
def _no_mx(monkeypatch):
    group_lists._mx_cache.clear()
    monkeypatch.setattr(group_lists, "mx_hosts", lambda domain: [])


def _status(conn, entity_id, address, status, observed_at, email_status=""):
    conn.execute(
        "INSERT OR REPLACE INTO external_status"
        " (entity_id, channel, address, status, email_status, source, observed_at)"
        " VALUES (?, 'google_groups', ?, ?, ?, 'test', ?)",
        (entity_id, address, status, email_status, observed_at),
    )


def _decision(conn, entity_id, address, status, channel="google_groups"):
    point_id = conn.execute(
        "SELECT id FROM contact_points WHERE value = ?", (address,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO decision_state"
        " (entity_id, contact_point_id, channel, status, source)"
        " VALUES (?, ?, ?, ?, 'test')",
        (entity_id, point_id, channel, status),
    )


def _read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _txt(path):
    return [line for line in path.read_text().splitlines() if line]


def _run(store, tmp_path):
    target_dir, run_dir = tmp_path / "wd", tmp_path / "bd"
    group_lists.build_group_lists(
        db_path=store["db"], target_dir=target_dir, run_dir=run_dir
    )
    return target_dir, run_dir


def test_dedupes_gmail_variants_and_marks_membership(store, tmp_path):
    entity_id = store["member"]("Dot Person", ["dot.person@gmail.com"])
    _status(store["conn"], entity_id, "dotperson@gmail.com", "member", "2026-09-23")
    store["conn"].commit()

    target_dir, run_dir = _run(store, tmp_path)

    target = _read(target_dir / "group_target.csv")
    assert [row["Email"] for row in target] == ["dot.person@gmail.com"]
    assert target[0]["In_Group"] == "yes"
    assert _read(target_dir / "group_remaining.csv") == []


def test_newest_snapshot_wins(store, tmp_path):
    entity_id = store["member"]("Snapshot Person", ["snap@example.com"])
    _status(store["conn"], entity_id, "snap@example.com", "invited", "2026-09-21")
    _status(store["conn"], entity_id, "snap@example.com", "member", "2026-09-23")
    store["conn"].commit()

    target_dir, run_dir = _run(store, tmp_path)

    assert _read(target_dir / "group_remaining.csv") == []
    assert "snap@example.com" in _txt(run_dir / "skip_members.txt")


def test_blocked_and_invite_required_routing(store, tmp_path):
    conn = store["conn"]
    blocked = store["member"]("Blocked Person", ["blocked@example.com"])
    forced = store["member"](
        "Forced Person", ["forced@gmail.com", "forced@illinois.edu"]
    )
    _decision(conn, blocked, "blocked@example.com", "blocked")
    _decision(conn, forced, "forced@illinois.edu", "invite_required")
    conn.commit()

    _, run_dir = _run(store, tmp_path)

    google = _txt(run_dir / "google_remaining.txt")
    other = _txt(run_dir / "other_remaining.txt")
    assert "blocked@example.com" not in google + other
    assert google == ["forced@gmail.com"]
    assert other == ["forced@illinois.edu"]


def test_manual_addresses_and_edu_last(store, tmp_path):
    conn = store["conn"]
    person = store["member"]("Manual Person", ["manual@example.com"], tracker="5001")
    store["member"]("Student Person", ["student@illinois.edu"])
    _decision(
        conn,
        person,
        "manual@example.com",
        "additional_address_confirmed",
        channel="manual_address_map",
    )
    conn.commit()

    target_dir, run_dir = _run(store, tmp_path)

    target = {row["Email"]: row for row in _read(target_dir / "group_target.csv")}
    assert target["manual@example.com"]["Sources"] == "manual,tracker"
    remaining = [row["Email"] for row in _read(target_dir / "group_remaining.csv")]
    assert remaining == ["manual@example.com", "student@illinois.edu"]
    assert _txt(run_dir / "other_remaining.txt") == [
        "manual@example.com",
        "student@illinois.edu",
    ]


def test_held_addresses_leave_the_target(store, tmp_path):
    conn = store["conn"]
    held = store["member"]("Held Person", ["held@example.com"])
    _decision(conn, held, "held@example.com", "held")
    conn.commit()

    target_dir, run_dir = _run(store, tmp_path)

    assert _read(target_dir / "group_target.csv") == []
    assert "held@example.com" in _txt(run_dir / "skip_members.txt")
    assert _txt(run_dir / "google_remaining.txt") == []


def test_invited_is_distinct_from_member_and_absent(store, tmp_path):
    """A pending invitation is not a member: not a recipient, not a resubmit."""
    conn = store["conn"]
    invited = store["member"]("Invited Person", ["invited@example.com"])
    store["member"]("Absent Person", ["absent@example.com"])
    _status(conn, invited, "invited@example.com", "invited", "2026-09-23")
    conn.commit()

    target_dir, run_dir = _run(store, tmp_path)

    target = {
        row["Email"]: row["In_Group"]
        for row in _read(target_dir / "group_target.csv")
    }
    assert target == {"invited@example.com": "invited", "absent@example.com": "no"}

    # Only the never-contacted address is submitted; the invite is left alone.
    remaining = [row["Email"] for row in _read(target_dir / "group_remaining.csv")]
    assert remaining == ["absent@example.com"]
    assert _txt(run_dir / "other_remaining.txt") == ["absent@example.com"]
    assert "invited@example.com" in _txt(run_dir / "skip_members.txt")


def test_invitation_is_not_a_member_even_with_a_member_variant(store, tmp_path):
    """A person can be a member on one address and merely invited on another."""
    conn = store["conn"]
    person = store["member"]("Two Addresses", ["two@gmail.com", "two@example.com"])
    _status(conn, person, "two@gmail.com", "member", "2026-09-23")
    _status(conn, person, "two@example.com", "invited", "2026-09-23")
    conn.commit()

    target_dir, _ = _run(store, tmp_path)

    target = {
        row["Email"]: row["In_Group"]
        for row in _read(target_dir / "group_target.csv")
    }
    assert target["two@gmail.com"] == "yes"
    assert target["two@example.com"] == "invited"
