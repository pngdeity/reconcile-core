import sqlite3
import contextlib
import os
from pathlib import Path
from typing import Optional
from .interfaces import BasePersistence

class SQLitePersistence(BasePersistence):
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            # Default path based on XDG_DATA_HOME or fallback to ~/.local/share
            data_home = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            db_path = Path(data_home) / "reconcile-core" / "identities.db"
        
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database schema if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS identity_map (
                    platform TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    google_resource_name TEXT NOT NULL,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (platform, source_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resource_name TEXT,
                    action TEXT,
                    delta TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS unresolved_identities (
                    platform TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    display_name TEXT,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (platform, source_id)
                )
            """)

    @contextlib.contextmanager
    def _connection(self):
        """Context manager for safe SQLite connection handling."""
        conn = sqlite3.connect(self.db_path)
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
            cursor = conn.execute(
                "SELECT google_resource_name FROM identity_map WHERE platform = ? AND source_id = ?",
                (platform, source_id)
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def set_mapping(self, platform: str, source_id: str, resource_name: str) -> None:
        """Store or update the mapping between a platform identity and a Google resourceName."""
        with self._connection() as conn:
            # Ensure it's removed from unresolved if it was there
            conn.execute("DELETE FROM unresolved_identities WHERE platform = ? AND source_id = ?", (platform, source_id))
            conn.execute(
                """
                INSERT INTO identity_map (platform, source_id, google_resource_name, last_seen)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(platform, source_id) DO UPDATE SET
                    google_resource_name = excluded.google_resource_name,
                    last_seen = CURRENT_TIMESTAMP
                """,
                (platform, source_id, resource_name)
            )

    def list_unresolved(self) -> list[tuple[str, str]]:
        """List all platform identities (platform, source_id) that haven't been resolved."""
        with self._connection() as conn:
            cursor = conn.execute("SELECT platform, source_id FROM unresolved_identities")
            return cursor.fetchall()

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
                (platform, source_id, display_name)
            )

    def log_audit(self, resource_name: str, action: str, delta: str) -> None:
        """Log a reconciliation action for auditing purposes."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO audit_log (resource_name, action, delta) VALUES (?, ?, ?)",
                (resource_name, action, delta)
            )
