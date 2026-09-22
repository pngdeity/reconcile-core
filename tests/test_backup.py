"""Tests for store backup/restore (C1). Synthetic, no PII."""

import pytest

from reconcile_core import cli
from reconcile_core.store import (
    add_contact_point,
    apply_migrations,
    connect,
    create_entity,
)
from reconcile_core.store.backup import (
    default_backup_path,
    restore,
    snapshot,
    verify,
)


def _seed(db):
    apply_migrations(db)
    conn = connect(db)
    try:
        entity_id = create_entity(conn, display_name="Jane Doe")
        add_contact_point(conn, entity_id, "email", "jane@example.com")
        conn.commit()
    finally:
        conn.close()
    return db


def test_snapshot_and_verify(tmp_path):
    db = _seed(tmp_path / "c.db")
    out = tmp_path / "snap.db"
    path = snapshot(db, out)
    assert path == out and out.exists()
    info = verify(out)
    assert info["integrity"] == "ok"
    assert info["schema_version"] == 1
    assert info["counts"]["entities"] == 1
    assert info["counts"]["contact_points"] == 1
    assert info["counts"] == verify(db)["counts"]


def test_snapshot_default_destination(tmp_path):
    db = _seed(tmp_path / "c.db")
    path = snapshot(db)
    assert path.parent == tmp_path / "backups"
    assert path.name.startswith("c-")
    assert path.suffix == ".db"
    assert default_backup_path(db).parent == tmp_path / "backups"


def test_snapshot_refuses_existing_destination(tmp_path):
    db = _seed(tmp_path / "c.db")
    out = tmp_path / "snap.db"
    snapshot(db, out)
    with pytest.raises(FileExistsError):
        snapshot(db, out)


def test_snapshot_missing_store(tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshot(tmp_path / "missing.db", tmp_path / "snap.db")


def test_restore_round_trip(tmp_path):
    db = _seed(tmp_path / "c.db")
    out = tmp_path / "snap.db"
    snapshot(db, out)

    conn = connect(db)
    try:
        create_entity(conn, display_name="Late Addition")
        conn.commit()
    finally:
        conn.close()
    assert verify(db)["counts"]["entities"] == 2

    assert restore(out, db, force=True) == db
    assert verify(db)["counts"]["entities"] == 1


def test_restore_refuses_clobber_without_force(tmp_path):
    db = _seed(tmp_path / "c.db")
    out = tmp_path / "snap.db"
    snapshot(db, out)
    with pytest.raises(FileExistsError):
        restore(out, db)
    assert restore(out, db, force=True) == db


def test_restore_rejects_non_store(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    with pytest.raises(ValueError):
        restore(junk, tmp_path / "dest.db")


def test_restore_missing_snapshot(tmp_path):
    with pytest.raises(FileNotFoundError):
        restore(tmp_path / "missing.db", tmp_path / "dest.db")


def test_cli_backup_and_restore(tmp_path, capsys):
    db = _seed(tmp_path / "c.db")
    snap = tmp_path / "snap.db"
    assert cli.main(["backup", "--db", str(db), "--out", str(snap)]) == 0
    assert snap.exists()
    assert "Snapshot written" in capsys.readouterr().out

    assert cli.main(["restore", str(snap), "--db", str(db), "--force"]) == 0
    assert "restored" in capsys.readouterr().out.lower()
