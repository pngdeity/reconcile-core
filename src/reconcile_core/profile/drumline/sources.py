"""Register ingest sources — the provenance root for roster claims.

Every `affiliations` row and every sourced name claim points at one `sources`
row plus a location inside it (`source_ref`, e.g. `r18:c17`). Registering the
source with its sha256 is what makes those references checkable later.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def sha256_file(path: Path | str) -> str:
    """Hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_source(
    conn: sqlite3.Connection,
    *,
    name: str,
    kind: str,
    url: str | None = None,
    path: Path | str | None = None,
    fetched_at: str | None = None,
    note: str | None = None,
) -> int:
    """Insert or update one source row and return its id.

    The digest comes from `path` when given, so the database always describes
    the artifact that is actually on disk.
    """
    sha256 = sha256_file(path) if path is not None else None
    conn.execute(
        """
        INSERT INTO sources (name, kind, url, fetched_at, sha256, note)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET kind = excluded.kind, url = excluded.url,
          fetched_at = coalesce(excluded.fetched_at, sources.fetched_at),
          sha256 = coalesce(excluded.sha256, sources.sha256),
          note = coalesce(excluded.note, sources.note)
        """,
        (name, kind, url, fetched_at, sha256, note),
    )
    row = conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
    return row[0]
