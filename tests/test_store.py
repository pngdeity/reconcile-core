"""Tests for the canonical contacts store (schema, migrations, helpers)."""


import pytest

from reconcile_core.store import migrate, store


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "contacts.db"


@pytest.fixture
def conn(db_path):
    migrate.apply_migrations(db_path)
    c = store.connect(db_path)
    yield c
    c.close()


def test_migrate_applies_and_is_idempotent(db_path):
    assert migrate.apply_migrations(db_path) == 1
    # Second run applies nothing and keeps the version.
    assert migrate.apply_migrations(db_path) == 1


def test_status_reports_applied(db_path):
    migrate.apply_migrations(db_path)
    status = migrate.status(db_path)
    assert status and all(applied for _, _, applied in status)


def test_foreign_keys_enforced(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_entity_and_uid(conn):
    alice = store.create_entity(
        conn, type="person", display_name="Alice Example", first_name="Alice"
    )
    row = conn.execute(
        "SELECT uid, type FROM entities WHERE id = ?", (alice,)
    ).fetchone()
    assert row["type"] == "person"
    assert len(row["uid"]) == 32


def test_external_ref_round_trip_and_conflict(conn):
    alice = store.create_entity(conn, display_name="Alice")
    bob = store.create_entity(conn, display_name="Bob")
    store.add_external_ref(conn, alice, "linkedin", "alice-slug")
    assert store.get_entity_by_ref(conn, "linkedin", "alice-slug") == alice
    # Same ref to the same entity is fine.
    store.add_external_ref(conn, alice, "linkedin", "alice-slug")
    # Same ref to a different entity is a conflict.
    with pytest.raises(ValueError):
        store.add_external_ref(conn, bob, "linkedin", "alice-slug")


def test_contact_points_and_address(conn):
    alice = store.create_entity(conn, display_name="Alice")
    cp = store.add_contact_point(
        conn,
        alice,
        "email",
        "alice@example.com",
        label_raw="* Home",
        label_norm="home",
        is_primary=True,
        position=1,
        source="test",
    )
    store.add_contact_point(conn, alice, "handle", "alice", service="linkedin")
    addr_cp = store.add_contact_point(conn, alice, "address", "1 Main St")
    store.add_address(conn, addr_cp, street="1 Main St", city="Urbana")
    n = conn.execute(
        "SELECT COUNT(*) FROM contact_points WHERE entity_id = ?", (alice,)
    ).fetchone()[0]
    has_addr = conn.execute(
        "SELECT 1 FROM addresses WHERE contact_point_id = ?", (addr_cp,)
    ).fetchone()
    assert n == 3
    assert has_addr is not None
    assert cp != addr_cp


def test_segment_membership_idempotent(conn):
    alice = store.create_entity(conn, display_name="Alice")
    seg = store.ensure_segment(conn, "alumni")
    assert store.ensure_segment(conn, "alumni") == seg
    store.add_segment_member(conn, seg, alice)
    store.add_segment_member(conn, seg, alice)
    n = conn.execute(
        "SELECT COUNT(*) FROM segment_members WHERE segment_id = ?", (seg,)
    ).fetchone()[0]
    assert n == 1


def test_decision_state(conn):
    alice = store.create_entity(conn, display_name="Alice")
    store.add_decision_state(conn, alice, "blocked", channel="google_groups")
    row = conn.execute(
        "SELECT status FROM decision_state WHERE entity_id = ?", (alice,)
    ).fetchone()
    assert row["status"] == "blocked"


@pytest.mark.parametrize(
    "call",
    [
        lambda conn: store.add_contact_point(conn, 1, "carrier_pigeon", "x"),
        lambda conn: store.create_entity(conn, type="robot"),
        lambda conn: store.create_entity(conn, type="person", nope="x"),
    ],
)
def test_validation_rejects_bad_input(conn, call):
    with pytest.raises(ValueError):
        call(conn)


def test_counts(conn):
    store.create_entity(conn, display_name="Alice")
    store.create_entity(conn, type="org", display_name="Org")
    c = store.counts(conn)
    assert c["entities"] == 2


def test_cascade_delete(db_path):
    migrate.apply_migrations(db_path)
    conn = store.connect(db_path)
    alice = store.create_entity(conn, display_name="Alice")
    store.add_contact_point(conn, alice, "email", "a@example.com")
    conn.commit()
    conn.execute("DELETE FROM entities WHERE id = ?", (alice,))
    conn.commit()
    orphans = conn.execute(
        "SELECT COUNT(*) FROM contact_points WHERE entity_id = ?", (alice,)
    ).fetchone()[0]
    conn.close()
    assert orphans == 0
