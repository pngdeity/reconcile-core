"""Tests for the unified CLI (B6). Synthetic, no PII."""

import pytest

import reconcile_core.main as main_module
from reconcile_core import cli
from reconcile_core.models import SocialHandle, StandardContact
from reconcile_core.store import connect, counts


class FakeAdapter:
    contacts: list[StandardContact] = []

    def extract(self, path):
        return iter(self.contacts)


@pytest.fixture
def fake_adapter(monkeypatch):
    monkeypatch.setitem(main_module.ADAPTER_CLASSES, "generic", FakeAdapter)
    FakeAdapter.contacts = []
    yield FakeAdapter
    FakeAdapter.contacts = []


def _count(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_migrate_creates_store(tmp_path, capsys):
    db = tmp_path / "c.db"
    assert cli.main(["migrate", "--db", str(db)]) == 0
    assert db.exists()
    assert "version" in capsys.readouterr().out


def test_migrate_status_and_profile(tmp_path, capsys):
    db = tmp_path / "c.db"
    assert cli.main(["migrate", "--db", str(db), "--status"]) == 0
    assert "version" in capsys.readouterr().out
    assert cli.main(["migrate", "--db", str(db), "--profile", "drumline"]) == 0
    conn = connect(db)
    try:
        version = _count(conn, "SELECT MAX(version) FROM schema_version")
    finally:
        conn.close()
    assert version == 2


def test_ingest_creates_entity(tmp_path, fake_adapter):
    db = tmp_path / "c.db"
    fake_adapter.contacts = [
        StandardContact(
            source_id="slug",
            display_name="Jane Doe",
            emails=["jane@example.com"],
            handles=[SocialHandle("github", "janedoe")],
        )
    ]
    assert cli.main(["ingest", "run.csv", "-p", "generic", "--db", str(db)]) == 0
    conn = connect(db)
    try:
        assert counts(conn)["entities"] == 1
        assert _count(conn, "SELECT COUNT(*) FROM contact_points") == 2
    finally:
        conn.close()


def test_ingest_is_idempotent(tmp_path, fake_adapter):
    db = tmp_path / "c.db"
    fake_adapter.contacts = [
        StandardContact(
            source_id="slug", display_name="Jane Doe", emails=["jane@example.com"]
        )
    ]
    cli.main(["ingest", "run.csv", "-p", "generic", "--db", str(db)])
    cli.main(["ingest", "run.csv", "-p", "generic", "--db", str(db)])
    conn = connect(db)
    try:
        assert counts(conn)["entities"] == 1
        assert _count(conn, "SELECT COUNT(*) FROM contact_points") == 1
    finally:
        conn.close()


def test_resolve_empty(tmp_path, capsys):
    db = tmp_path / "c.db"
    assert cli.main(["resolve", "--db", str(db)]) == 0
    assert "No unresolved" in capsys.readouterr().out


def test_export_google_contacts(tmp_path, fake_adapter):
    db = tmp_path / "c.db"
    out = tmp_path / "out"
    fake_adapter.contacts = [
        StandardContact(source_id="1", display_name="Jane", emails=["jane@example.com"])
    ]
    cli.main(["ingest", "run.csv", "-p", "generic", "--db", str(db)])
    conn = connect(db)
    try:
        conn.execute(
            "INSERT INTO external_refs (entity_id, source, ref_value)"
            " SELECT id, 'google', '1' FROM entities"
        )
        conn.commit()
    finally:
        conn.close()

    assert (
        cli.main(["export", "google-contacts", "--out", str(out), "--db", str(db)]) == 0
    )
    assert (out / "Contacts.csv").exists()
    assert (out / "Contacts_import.csv").exists()


def test_export_drumline_members(tmp_path):
    db = tmp_path / "c.db"
    cli.main(["migrate", "--db", str(db), "--profile", "drumline"])
    out = tmp_path / "dm.csv"
    assert (
        cli.main(["export", "drumline-members", "--out", str(out), "--db", str(db)])
        == 0
    )
    assert out.exists()


def test_audit(tmp_path, fake_adapter, capsys):
    db = tmp_path / "c.db"
    fake_adapter.contacts = [
        StandardContact(source_id="1", display_name="Jane", emails=["jane@example.com"])
    ]
    cli.main(["ingest", "run.csv", "-p", "generic", "--db", str(db)])
    assert cli.main(["audit", "--db", str(db)]) == 0
    assert "entities" in capsys.readouterr().out.lower()


def test_reconcile_dry_run_then_apply(tmp_path, fake_adapter):
    db = tmp_path / "c.db"
    fake_adapter.contacts = [
        StandardContact(
            source_id="slug", display_name="Jane Doe", emails=["jane@example.com"]
        )
    ]
    cli.main(["ingest", "run.csv", "-p", "generic", "--db", str(db)])

    fake_adapter.contacts = [
        StandardContact(
            source_id="slug",
            display_name="Jane Doe",
            emails=["jane@example.com"],
            phones=["+1 555 0100"],
        )
    ]
    assert (
        cli.main(
            ["reconcile", "run.csv", "-p", "generic", "--db", str(db), "--dry-run"]
        )
        == 0
    )
    conn = connect(db)
    try:
        assert (
            _count(conn, "SELECT COUNT(*) FROM contact_points WHERE kind='phone'") == 0
        )
    finally:
        conn.close()

    assert (
        cli.main(["reconcile", "run.csv", "-p", "generic", "--db", str(db), "--apply"])
        == 0
    )
    conn = connect(db)
    try:
        assert (
            _count(conn, "SELECT COUNT(*) FROM contact_points WHERE kind='phone'") == 1
        )
    finally:
        conn.close()
