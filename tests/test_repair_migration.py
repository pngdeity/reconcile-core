"""Tests for the core schema repair migration (0003)."""

import sqlite3

from reconcile_core.store.import_db import import_legacy_db
from reconcile_core.store.migrate import apply_migrations

REPAIRED = {"audit_log", "unresolved_identities"}


def _tables(path) -> set[str]:
    conn = sqlite3.connect(str(path))
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()


def test_repair_migration_restores_dropped_tables(tmp_path):
    db = tmp_path / "c.db"
    apply_migrations(db)

    conn = sqlite3.connect(str(db))
    conn.execute("DROP TABLE audit_log")
    conn.execute("DROP TABLE unresolved_identities")
    conn.execute("DELETE FROM schema_version WHERE version = 3")
    conn.commit()
    conn.close()
    assert not (REPAIRED & _tables(db))

    apply_migrations(db)

    assert REPAIRED <= _tables(db)


def test_legacy_imported_store_self_heals(tmp_path):
    src = tmp_path / "legacy.db"
    dst = tmp_path / "contacts.db"

    conn = sqlite3.connect(str(src))
    conn.executescript(
        """
        CREATE TABLE entities (id INTEGER PRIMARY KEY, display_name TEXT);
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY, name TEXT,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO schema_version (version, name) VALUES (1, 'init');
        """
    )
    conn.commit()
    conn.close()

    import_legacy_db(src, dst)
    assert not (REPAIRED & _tables(dst))

    apply_migrations(dst)

    assert REPAIRED <= _tables(dst)
