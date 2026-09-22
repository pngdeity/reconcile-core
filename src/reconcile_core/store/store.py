"""Low-level helpers for the canonical contacts store (SQLite).

The store is the single source of truth for entities and their contact points.
Generated files are projections; nothing should treat them as authoritative.

Schema: ``store/migrations/*.sql`` — create/upgrade via ``store.migrate``.
"""

import os
import sqlite3
import uuid
from pathlib import Path

ENTITY_TYPES = ("person", "org", "service", "group")
KINDS = ("email", "phone", "address", "url", "handle")

ENTITY_FIELDS = (
    "display_name",
    "first_name",
    "middle_name",
    "last_name",
    "nickname",
    "org_name",
    "title",
    "department",
    "birthday",
    "notes",
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_DB_PATH = REPO_ROOT / "var" / "contacts.db"


def default_db_path() -> Path:
    """Default location of the canonical store.

    Repo-local (``var/contacts.db``) for now; override with the
    ``RECONCILE_CORE_DB`` environment variable. ADR-0002 settles an XDG default
    (roadmap C7); until it lands, the repo-local path is authoritative.
    """
    override = os.environ.get("RECONCILE_CORE_DB")
    if override:
        return Path(override).expanduser()
    return REPO_DB_PATH


DEFAULT_DB = default_db_path()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DEFAULT_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def mint_uid() -> str:
    """Opaque internal identifier. Never reused."""
    return uuid.uuid4().hex


def create_entity(
    conn: sqlite3.Connection,
    *,
    type: str = "person",
    privacy_tier: str = "standard",
    uid: str | None = None,
    **fields,
) -> int:
    if type not in ENTITY_TYPES:
        raise ValueError(f"invalid entity type: {type!r}")
    unknown = set(fields) - set(ENTITY_FIELDS)
    if unknown:
        raise ValueError(f"unknown entity fields: {sorted(unknown)}")
    columns = ["uid", "type", "privacy_tier", *fields]
    values = [uid or mint_uid(), type, privacy_tier, *fields.values()]
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO entities ({', '.join(columns)}) VALUES ({placeholders})", values
    )
    return cur.lastrowid


def get_entity_by_ref(
    conn: sqlite3.Connection, source: str, ref_value: str
) -> int | None:
    row = conn.execute(
        "SELECT entity_id FROM external_refs WHERE source = ? AND ref_value = ?",
        (source, str(ref_value)),
    ).fetchone()
    return row["entity_id"] if row else None


def add_external_ref(
    conn: sqlite3.Connection, entity_id: int, source: str, ref_value: str
) -> int:
    existing = get_entity_by_ref(conn, source, ref_value)
    if existing is not None:
        if existing != entity_id:
            raise ValueError(
                f"ref {source}:{ref_value} already maps to entity {existing}, "
                f"not {entity_id}"
            )
        return existing
    cur = conn.execute(
        "INSERT INTO external_refs (entity_id, source, ref_value) VALUES (?, ?, ?)",
        (entity_id, source, str(ref_value)),
    )
    return cur.lastrowid


def add_contact_point(
    conn: sqlite3.Connection,
    entity_id: int,
    kind: str,
    value: str,
    *,
    label_raw: str | None = None,
    label_norm: str | None = None,
    service: str | None = None,
    is_primary: bool = False,
    position: int | None = None,
    source: str | None = None,
) -> int:
    if kind not in KINDS:
        raise ValueError(f"invalid contact point kind: {kind!r}")
    cur = conn.execute(
        """
        INSERT INTO contact_points
          (entity_id, kind, value, label_raw, label_norm, service,
           is_primary, position, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            kind,
            value,
            label_raw,
            label_norm,
            service,
            1 if is_primary else 0,
            position,
            source,
        ),
    )
    return cur.lastrowid


def add_address(
    conn: sqlite3.Connection,
    contact_point_id: int,
    *,
    street: str | None = None,
    city: str | None = None,
    region: str | None = None,
    postal: str | None = None,
    country: str | None = None,
    pobox: str | None = None,
    extended: str | None = None,
    formatted: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO addresses
          (contact_point_id, street, city, region, postal, country, pobox,
           extended, formatted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_point_id,
            street,
            city,
            region,
            postal,
            country,
            pobox,
            extended,
            formatted,
        ),
    )


def add_alias(
    conn: sqlite3.Connection,
    entity_id: int,
    alias_type: str,
    alias_value: str,
    *,
    source: str | None = None,
    position: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO aliases "
        "(entity_id, alias_type, alias_value, source, position) VALUES (?, ?, ?, ?, ?)",
        (entity_id, alias_type, alias_value, source, position),
    )
    return cur.lastrowid


def ensure_segment(
    conn: sqlite3.Connection,
    name: str,
    *,
    description: str | None = None,
    definition: str | None = None,
) -> int:
    row = conn.execute("SELECT id FROM segments WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO segments (name, description, definition) VALUES (?, ?, ?)",
        (name, description, definition),
    )
    return cur.lastrowid


def add_segment_member(
    conn: sqlite3.Connection, segment_id: int, entity_id: int
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO segment_members (segment_id, entity_id) VALUES (?, ?)",
        (segment_id, entity_id),
    )


def add_decision_state(
    conn: sqlite3.Connection,
    entity_id: int,
    status: str,
    *,
    channel: str | None = None,
    contact_point_id: int | None = None,
    reason: str | None = None,
    source: str | None = None,
    observed_at: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO decision_state
          (entity_id, contact_point_id, channel, status, reason, source, observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (entity_id, contact_point_id, channel, status, reason, source, observed_at),
    )
    return cur.lastrowid


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "entities",
        "external_refs",
        "contact_points",
        "addresses",
        "aliases",
        "segments",
        "segment_members",
        "decision_state",
    )
    return {
        table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in tables
    }
