"""Snapshot and restore the canonical contacts store.

The store is the source of truth, lives in a git-ignored PII-bearing file, and
has no other copy; these helpers give it a cheap, consistent backup path.

Snapshots use SQLite's ``VACUUM INTO``, which writes a complete copy (including
committed WAL content) to a new file without blocking readers. Restore verifies
the snapshot is a real store before replacing the destination.

Library use:
    from reconcile_core.store.backup import snapshot, restore, verify
    snapshot()                                  # -> <store-dir>/backups/<name>-<stamp>.db
    restore("snapshot.db", force=True)

CLI:
    uv run python -m reconcile_core.store.backup [--db PATH] [--out PATH]
    uv run python -m reconcile_core.store.backup --restore FILE [--db PATH] [--force]
    uv run python -m reconcile_core.store.backup --verify [--db PATH]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .store import default_db_path

COUNTED_TABLES = (
    "entities",
    "external_refs",
    "contact_points",
    "addresses",
    "aliases",
    "segments",
    "segment_members",
    "decision_state",
)


def default_backup_path(db_path: Path | str | None = None) -> Path:
    """Return ``<store-dir>/backups/<store-stem>-<timestamp>.db``."""
    path = Path(db_path) if db_path is not None else default_db_path()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.parent / "backups" / f"{path.stem}-{stamp}.db"


def verify(db_path: Path | str) -> dict:
    """Validate that ``db_path`` is an intact contacts store; return a summary."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"not a SQLite database: {path}") from exc
        if integrity != "ok":
            raise ValueError(f"integrity check failed for {path}: {integrity}")

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "entities" not in tables:
            raise ValueError(f"not a contacts store (no entities table): {path}")

        version = 0
        if "schema_version" in tables:
            row = conn.execute(
                "SELECT MAX(version) AS v FROM schema_version"
            ).fetchone()
            version = row["v"] or 0

        table_counts = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in COUNTED_TABLES
            if table in tables
        }
        return {
            "path": str(path),
            "integrity": integrity,
            "schema_version": version,
            "counts": table_counts,
        }
    finally:
        conn.close()


def snapshot(db_path: Path | str | None = None, dest: Path | str | None = None) -> Path:
    """Write an atomic, consistent copy of the store to ``dest``."""
    src = Path(db_path) if db_path is not None else default_db_path()
    if not src.exists():
        raise FileNotFoundError(f"database not found: {src}")
    verify(src)
    out = Path(dest) if dest is not None else default_backup_path(src)
    if out.exists():
        raise FileExistsError(f"snapshot already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(src))
    try:
        conn.isolation_level = None
        conn.execute("VACUUM INTO ?", (str(out),))
    finally:
        conn.close()
    return out


def restore(
    source: Path | str, dest: Path | str | None = None, *, force: bool = False
) -> Path:
    """Replace the store at ``dest`` with a verified snapshot from ``source``."""
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(f"snapshot not found: {src}")
    verify(src)
    dst = Path(dest) if dest is not None else default_db_path()
    if dst.exists() and not force:
        raise FileExistsError(f"destination exists: {dst} (pass --force to overwrite)")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Drop stale sidecars so the restored file is not combined with an old WAL.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{dst}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    tmp = Path(f"{dst}.restore-tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)
    return dst


def _print_report(info: dict) -> None:
    summary = ", ".join(f"{key}={value}" for key, value in info["counts"].items())
    print(f"Store: {info['path']}")
    print(f"  integrity: {info['integrity']}")
    print(f"  schema version: {info['schema_version']}")
    print(f"  counts: {summary or 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot or restore the contacts store"
    )
    parser.add_argument("--db", default=str(default_db_path()), help="store path")
    parser.add_argument(
        "--out",
        help="snapshot destination (default: <store-dir>/backups/<name>-<stamp>.db)",
    )
    parser.add_argument("--restore", metavar="FILE", help="restore the store from FILE")
    parser.add_argument(
        "--verify", action="store_true", help="validate the store and exit"
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite the store on restore"
    )
    args = parser.parse_args()

    if args.verify:
        _print_report(verify(args.db))
        return 0
    if args.restore:
        dest = restore(args.restore, args.db, force=args.force)
        print(f"Restored {args.restore} -> {dest}")
        return 0

    out = snapshot(args.db, args.out)
    print(f"Snapshot written to {out}")
    _print_report(verify(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
