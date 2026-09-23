"""Import a Google Groups membership export into ``external_status``.

Reads an export with a title line, a header and one row per address
(``Email address, Nickname, Group status, Email status, ...``), records a dated
snapshot per address and links each to a store entity by email when possible.

Idempotent per day: re-running replaces the same-day snapshot.

Usage:
    uv run python -m reconcile_core.profile.drumline import-group-status \
        --input group-membership.csv --db var/contacts.db
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from ...store import connect

CHANNEL = "google_groups"
SOURCE = "group-membership.csv"


def norm(email: str) -> str:
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        return local.replace(".", "") + "@gmail.com"
    return email


def load_export(path: Path | str) -> list[tuple[str, str, str, str]]:
    """Return (address, nickname, group_status, email_status) from the export."""
    out = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) < 3 or "@" not in row[0]:
                continue
            out.append(
                (
                    row[0].strip().lower(),
                    (row[1] or "").strip(),
                    (row[2] or "").strip().lower(),
                    (row[3] or "").strip().lower() if len(row) > 3 else "",
                )
            )
    return out


def email_index(conn) -> dict[str, int]:
    """Gmail-normalized email -> entity id (first match wins)."""
    index: dict[str, int] = {}
    for row in conn.execute(
        "SELECT entity_id, value FROM contact_points WHERE kind = 'email'"
    ):
        index.setdefault(norm(row["value"]), row["entity_id"])
    return index


def import_group_status(input_path, db_path=None, observed_at=None) -> dict:
    day = observed_at or date.today().isoformat()
    entries = load_export(input_path)
    conn = connect(db_path)
    try:
        index = email_index(conn)
        linked = 0
        by_status: dict[str, int] = {}
        for address, nickname, status, email_status in entries:
            entity_id = index.get(norm(address))
            if entity_id:
                linked += 1
            by_status[status] = by_status.get(status, 0) + 1
            conn.execute(
                "INSERT OR REPLACE INTO external_status"
                " (entity_id, channel, address, status, email_status, nickname,"
                "  source, observed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entity_id,
                    CHANNEL,
                    address,
                    status,
                    email_status,
                    nickname,
                    SOURCE,
                    day,
                ),
            )
        obs = conn.execute(
            "SELECT MAX(observed_at) AS d FROM external_status WHERE channel = ?",
            (CHANNEL,),
        ).fetchone()["d"]
        conn.commit()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM external_status WHERE channel = ? AND observed_at = ?",
            (CHANNEL, day),
        ).fetchone()["n"]
    finally:
        conn.close()
    return {
        "rows": len(entries),
        "linked": linked,
        "snapshot": total,
        "observed_at": day,
        "latest": obs,
        "by_status": by_status,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a Google Groups membership export into external_status"
    )
    parser.add_argument("--input", required=True, help="group-membership.csv path")
    parser.add_argument("--db", default=None)
    parser.add_argument("--date", default=None, help="snapshot date (default: today)")
    args = parser.parse_args(argv)
    stats = import_group_status(args.input, args.db, args.date)
    print(f"Imported {stats['rows']} rows from {args.input}")
    print(
        f"  snapshot {stats['observed_at']}: {stats['snapshot']} addresses "
        f"({stats['linked']} linked to entities)"
    )
    print(f"  by status: {stats['by_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
