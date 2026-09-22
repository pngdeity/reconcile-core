"""Apply numbered SQL migrations to the canonical contacts store.

Idempotent: already-applied migrations are skipped. Each migration runs inside
a transaction; a migration file must not contain BEGIN/COMMIT. The runner owns
the `schema_version` table.

Library use:
    from reconcile_core.store.migrate import apply_migrations
    apply_migrations(db_path)

CLI:
    uv run python -m reconcile_core.store.migrate [--db PATH] [--status]
"""

import argparse
import re
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path

from .store import default_db_path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATION_RE = re.compile(r"^(\d+)_(.+)\.sql$")

VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def discover(
    extra_dirs: Iterable[Path | str] | None = None,
) -> list[tuple[int, str, Path]]:
    """Discover migrations in the core dir plus any profile dirs (sorted by version)."""
    directories = [MIGRATIONS_DIR] + [Path(d) for d in (extra_dirs or [])]
    found: list[tuple[int, str, Path]] = []
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.sql")):
            match = MIGRATION_RE.match(path.name)
            if not match:
                raise ValueError(
                    f"Bad migration filename (expected NNNN_name.sql): {path.name}"
                )
            found.append((int(match.group(1)), match.group(2), path))
    found.sort(key=lambda item: item[0])
    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"Duplicate migration versions: {versions}")
    return found


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(VERSION_DDL)
    return {row[0] for row in conn.execute("SELECT version FROM schema_version")}


def apply_migration(
    conn: sqlite3.Connection, version: int, name: str, path: Path
) -> None:
    sql = path.read_text()
    try:
        conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
    except Exception:
        conn.rollback()
        raise
    with conn:
        conn.execute(
            "INSERT INTO schema_version (version, name) VALUES (?, ?)", (version, name)
        )


def apply_migrations(
    db_path: Path | str | None = None,
    extra_dirs: Iterable[Path | str] | None = None,
) -> int:
    """Apply all pending migrations; return the resulting schema version."""
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        applied = applied_versions(conn)
        pending = [(v, n, p) for v, n, p in discover(extra_dirs) if v not in applied]
        for version, name, migration_path in pending:
            apply_migration(conn, version, name, migration_path)
        return max(applied_versions(conn)) if applied_versions(conn) else 0
    finally:
        conn.close()


def status(
    db_path: Path | str | None = None,
    extra_dirs: Iterable[Path | str] | None = None,
) -> list[tuple[int, str, bool]]:
    """Return (version, name, applied) for every discovered migration."""
    path = Path(db_path) if db_path is not None else default_db_path()
    conn = connect(path)
    try:
        applied = applied_versions(conn)
        return [(v, n, v in applied) for v, n, _ in discover(extra_dirs)]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply contacts-store migrations")
    parser.add_argument("--db", default=str(default_db_path()), help="database path")
    parser.add_argument("--status", action="store_true", help="show status only")
    args = parser.parse_args()

    db_path = Path(args.db)
    migrations = discover()
    conn = connect(db_path)
    try:
        applied = applied_versions(conn)
        if args.status:
            print(f"Database: {db_path}")
            for version, name, _ in migrations:
                state = "applied" if version in applied else "pending"
                print(f"  {version:04d}  {name:32s} {state}")
            print(f"Current version: {max(applied) if applied else 0}")
            return 0
    finally:
        conn.close()

    version = apply_migrations(db_path)
    print(f"Now at version {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
