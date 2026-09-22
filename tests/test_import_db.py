"""Tests for the legacy-store import and its migration re-stamp (B4)."""

import sqlite3

import pytest

from reconcile_core.store.import_db import BASELINE_VERSION, import_legacy_db
from reconcile_core.store.migrate import apply_migrations


def _make_legacy_store(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE entities (id INTEGER PRIMARY KEY, display_name TEXT);
        CREATE TABLE external_refs (
            id INTEGER PRIMARY KEY, entity_id INTEGER, source TEXT, ref_value TEXT
        );
        CREATE TABLE contact_points (id INTEGER PRIMARY KEY, entity_id INTEGER);
        CREATE TABLE segments (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE drumline_outreach (entity_id INTEGER PRIMARY KEY);
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY, name TEXT,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO schema_version (version, name) VALUES
            (1, 'init'), (2, 'aliases_position'),
            (3, 'external_status'), (4, 'drumline_outreach');
        INSERT INTO entities (id, display_name) VALUES (1, 'Legacy Person');
        """
    )
    conn.commit()
    conn.close()


def test_import_restamps_baseline_and_preserves_data(tmp_path):
    src = tmp_path / "legacy.db"
    dst = tmp_path / "contacts.db"
    _make_legacy_store(src)

    result = import_legacy_db(src, dst)

    assert result["baseline"] == BASELINE_VERSION
    assert dst.exists()

    conn = sqlite3.connect(str(dst))
    try:
        versions = conn.execute("SELECT version FROM schema_version").fetchall()
        assert versions == [(1,)]
        assert conn.execute("SELECT display_name FROM entities").fetchone() == (
            "Legacy Person",
        )
        # the unowned legacy table survives the import
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'drumline_outreach'"
            ).fetchone()
            is not None
        )
    finally:
        conn.close()


def test_import_does_not_shadow_future_migrations(tmp_path):
    src = tmp_path / "legacy.db"
    dst = tmp_path / "contacts.db"
    _make_legacy_store(src)

    import_legacy_db(src, dst)

    # only the consolidated baseline is applied, so the migrator is a no-op now
    # and any future migration (e.g. a drumline_outreach migration) still applies.
    assert apply_migrations(dst) == BASELINE_VERSION


def test_import_requires_force_to_overwrite(tmp_path):
    src = tmp_path / "legacy.db"
    dst = tmp_path / "contacts.db"
    _make_legacy_store(src)
    import_legacy_db(src, dst)

    with pytest.raises(FileExistsError):
        import_legacy_db(src, dst)

    # explicit overwrite succeeds
    import_legacy_db(src, dst, overwrite=True)


def test_import_rejects_non_store(tmp_path):
    src = tmp_path / "not-a-store.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE something (id INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError):
        import_legacy_db(src, tmp_path / "contacts.db")
