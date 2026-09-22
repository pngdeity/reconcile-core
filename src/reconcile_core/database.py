"""Store-backed persistence for reconcile-core.

Historically this module kept a separate ``identity_map`` table mapping
(platform, source_id) -> Google resourceName. That has been unified into the
canonical contacts store: every platform identity is an ``external_refs`` row on
an entity, and the Google resourceName is the entity's ``google`` ref. One entity
can therefore carry many platform identities, which is what lets the reconciler
merge a person across sources.
"""

import contextlib
import sqlite3
from pathlib import Path
from typing import Optional

from .interfaces import BasePersistence
from .store import store as _store
from .store.migrate import apply_migrations

GOOGLE_REF_SOURCE = "google"


def default_db_path() -> Path:
    return _store.default_db_path()


class SQLitePersistence(BasePersistence):
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self._init_db()

    def _init_db(self) -> None:
        """Create/upgrade the store schema."""
        apply_migrations(self.db_path)

    @contextlib.contextmanager
    def _connection(self):
        """Context manager for safe SQLite connection handling."""
        conn = _store.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_resource_name(self, platform: str, source_id: str) -> Optional[str]:
        """Retrieve the Google resourceName for a given platform identity."""
        with self._connection() as conn:
            entity_id = _store.get_entity_by_ref(conn, platform, source_id)
            if entity_id is None:
                return None
            row = conn.execute(
                "SELECT ref_value FROM external_refs WHERE entity_id = ? AND source = ?"
                " ORDER BY id DESC LIMIT 1",
                (entity_id, GOOGLE_REF_SOURCE),
            ).fetchone()
            return row["ref_value"] if row else None

    def set_mapping(self, platform: str, source_id: str, resource_name: str) -> None:
        """Store the mapping between a platform identity and a Google resourceName.

        Converges on an existing entity when either the platform identity or the
        Google resource is already known; otherwise creates a new person entity.
        """
        with self._connection() as conn:
            entity_id = _store.get_entity_by_ref(conn, GOOGLE_REF_SOURCE, resource_name)
            if entity_id is None:
                entity_id = _store.get_entity_by_ref(conn, platform, source_id)
            if entity_id is None:
                entity_id = _store.create_entity(
                    conn, type="person", display_name=str(source_id)
                )
            _store.add_external_ref(conn, entity_id, platform, source_id)
            # Keep a single Google ref per entity.
            conn.execute(
                "DELETE FROM external_refs WHERE entity_id = ? AND source = ?",
                (entity_id, GOOGLE_REF_SOURCE),
            )
            _store.add_external_ref(conn, entity_id, GOOGLE_REF_SOURCE, resource_name)
            conn.execute(
                "DELETE FROM unresolved_identities WHERE platform = ? AND source_id = ?",
                (platform, source_id),
            )

    def list_unresolved(self) -> list[tuple[str, str]]:
        """List all platform identities (platform, source_id) that haven't been resolved."""
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT platform, source_id FROM unresolved_identities"
            )
            return [tuple(row) for row in cursor.fetchall()]

    def mark_unresolved(self, platform: str, source_id: str, display_name: str) -> None:
        """Store an identity that couldn't be automatically mapped."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO unresolved_identities (platform, source_id, display_name, last_seen)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(platform, source_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    last_seen = CURRENT_TIMESTAMP
                """,
                (platform, source_id, display_name),
            )

    def log_audit(self, resource_name: str, action: str, delta: str) -> None:
        """Log a reconciliation action for auditing purposes."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO audit_log (resource_name, action, delta) VALUES (?, ?, ?)",
                (resource_name, action, delta),
            )
