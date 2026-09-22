"""One-time import of a legacy contacts store into the canonical store.

The legacy DB (illini) carries its own migration history (versions 1-4) that
does not line up with this package's consolidated baseline (``0001_init.sql``
folds illini's 1-3). Copying it verbatim would let legacy version numbers
shadow this package's future migrations, so the import re-stamps
``schema_version`` to the baseline. Tables that the consolidated baseline does
not own (currently ``drumline_outreach``) remain in place and become pending
migrations once their migration is added.

Library use:
    from reconcile_core.store.import_db import import_legacy_db
    import_legacy_db("path/to/legacy.db")

CLI:
    uv run python -m reconcile_core.store.import_db --source PATH [--db PATH] [--force]
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from .store import default_db_path

BASELINE_VERSION = 1
BASELINE_NAME = "init"

VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def import_legacy_db(
    source: Path | str,
    dest: Path | str | None = None,
    *,
    baseline: int = BASELINE_VERSION,
    overwrite: bool = False,
) -> dict:
    """Copy a legacy store to ``dest`` and re-stamp its migration baseline."""
    src = Path(source)
    dst = Path(dest) if dest is not None else default_db_path()

    if not src.exists():
        raise FileNotFoundError(f"source database not found: {src}")
    if dst.exists():
        if not overwrite:
            raise FileExistsError(
                f"destination exists: {dst} (pass --force to overwrite)"
            )
        dst.unlink()

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    conn = sqlite3.connect(str(dst))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "entities" not in tables:
            raise ValueError(
                f"source is not a contacts store (no entities table): {src}"
            )

        conn.execute(VERSION_DDL)
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version, name) VALUES (?, ?)",
            (baseline, BASELINE_NAME),
        )
        conn.commit()

        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("entities", "external_refs", "contact_points", "segments")
            if table in tables
        }
        return {
            "source": str(src),
            "dest": str(dst),
            "baseline": baseline,
            "tables": sorted(tables),
            "counts": counts,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a legacy contacts store")
    parser.add_argument("--source", required=True, help="legacy database path")
    parser.add_argument("--db", default=str(default_db_path()), help="destination path")
    parser.add_argument("--force", action="store_true", help="overwrite destination")
    args = parser.parse_args()

    result = import_legacy_db(args.source, args.db, overwrite=args.force)
    print(f"Imported {result['source']} -> {result['dest']}")
    print(f"  migration baseline re-stamped to {result['baseline']}")
    print(f"  counts: {result['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
