"""Bridge between adapter payloads (``StandardContact``) and the canonical store.

Adapters emit ``StandardContact`` objects. This module resolves each one to an
entity and unions its data into the store with zero loss, and reconstructs a
``StandardContact`` from stored contact points so the reconciler can compare a
proposed contact against a *store record*.

Storage mapping (``imClients`` have no dedicated table, so they use the reserved
``IM_SERVICE`` value on a ``handle`` point):

- emails   -> ``contact_points(kind='email')``
- phones   -> ``contact_points(kind='phone')``
- urls     -> ``contact_points(kind='url')``
- handles  -> ``contact_points(kind='handle', service=<platform>)``
- imClients-> ``contact_points(kind='handle', service='im')``
"""

from __future__ import annotations

import re
import sqlite3

from ..models import SocialHandle, StandardContact
from . import store as _store

IM_SERVICE = "im"
SOURCE = "bridge"
ENTITY_ID_PREFIX = "entity:"

_GOOGLE_REF = "google"


def _norm_email(value: str) -> str:
    return value.strip().lower()


def _norm_phone(value: str) -> str:
    return re.sub(r"[^0-9]", "", value.lstrip("+"))


def _norm_url(value: str) -> str:
    return value.strip().rstrip("/").lower()


def _norm_handle(platform: str, username: str) -> tuple[str, str]:
    return (platform.strip().lower(), username.strip().lower())


def find_entity_by_email(conn: sqlite3.Connection, email: str) -> int | None:
    """Resolve an entity by any of its email contact points (case-insensitive)."""
    if not email or not email.strip():
        return None
    row = conn.execute(
        "SELECT entity_id FROM contact_points"
        " WHERE kind = 'email' AND lower(value) = ? ORDER BY id LIMIT 1",
        (_norm_email(email),),
    ).fetchone()
    return row["entity_id"] if row else None


def _existing_sets(conn: sqlite3.Connection, entity_id: int):
    emails: set[str] = set()
    phones: set[str] = set()
    urls: set[str] = set()
    handles: set[tuple[str, str]] = set()
    ims: set[str] = set()
    for row in conn.execute(
        "SELECT kind, value, service FROM contact_points WHERE entity_id = ?",
        (entity_id,),
    ):
        kind, value, service = row["kind"], row["value"], (row["service"] or "")
        if kind == "email":
            emails.add(_norm_email(value))
        elif kind == "phone":
            phones.add(_norm_phone(value))
        elif kind == "url":
            urls.add(_norm_url(value))
        elif kind == "handle":
            if service == IM_SERVICE:
                ims.add(value.strip().lower())
            else:
                handles.add(_norm_handle(service, value))
    return emails, phones, urls, handles, ims


def _has_primary(conn: sqlite3.Connection, entity_id: int, kind: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM contact_points WHERE entity_id = ? AND kind = ?"
            " AND is_primary = 1 LIMIT 1",
            (entity_id, kind),
        ).fetchone()
        is not None
    )


def write_contact(
    conn: sqlite3.Connection,
    contact: StandardContact,
    *,
    platform: str | None = None,
    source_id: str | None = None,
    source: str = SOURCE,
    resolve_by_email: bool = True,
    entity_id: int | None = None,
) -> dict:
    """Resolve ``contact`` to an entity and union its data in (zero loss).

    Resolution order: an explicit ``entity_id``, then the ``(platform, source_id)``
    external ref, then a matching email contact point, then a new person entity.
    Returns a stats dict: ``{"entity_id", "created", "added": {kind: n}}``.
    """
    sid = source_id if source_id is not None else contact.source_id

    if entity_id is None and platform and sid:
        entity_id = _store.get_entity_by_ref(conn, platform, str(sid))

    if entity_id is None and resolve_by_email:
        for email in contact.emails:
            entity_id = find_entity_by_email(conn, email)
            if entity_id is not None:
                break

    created = False
    if entity_id is None:
        entity_id = _store.create_entity(
            conn, type="person", display_name=contact.display_name or str(sid or "")
        )
        created = True

    if platform and sid and _store.get_entity_by_ref(conn, platform, str(sid)) is None:
        _store.add_external_ref(conn, entity_id, platform, str(sid))

    emails, phones, urls, handles, ims = _existing_sets(conn, entity_id)
    added = {"emails": 0, "phones": 0, "urls": 0, "handles": 0, "imClients": 0}

    primary_email = not _has_primary(conn, entity_id, "email")
    primary_phone = not _has_primary(conn, entity_id, "phone")

    for position, email in enumerate(contact.emails):
        if not email.strip() or _norm_email(email) in emails:
            continue
        emails.add(_norm_email(email))
        _store.add_contact_point(
            conn,
            entity_id,
            "email",
            email,
            source=source,
            position=position,
            is_primary=primary_email,
        )
        primary_email = False
        added["emails"] += 1

    for position, phone in enumerate(contact.phones):
        if not phone.strip() or _norm_phone(phone) in phones:
            continue
        phones.add(_norm_phone(phone))
        _store.add_contact_point(
            conn,
            entity_id,
            "phone",
            phone,
            source=source,
            position=position,
            is_primary=primary_phone,
        )
        primary_phone = False
        added["phones"] += 1

    for url in contact.urls:
        if not url.strip() or _norm_url(url) in urls:
            continue
        urls.add(_norm_url(url))
        _store.add_contact_point(conn, entity_id, "url", url, source=source)
        added["urls"] += 1

    for handle in contact.handles:
        if not handle.username.strip():
            continue
        key = _norm_handle(handle.platform, handle.username)
        if key in handles:
            continue
        handles.add(key)
        _store.add_contact_point(
            conn,
            entity_id,
            "handle",
            handle.username,
            service=handle.platform.strip().lower(),
            source=source,
        )
        added["handles"] += 1
        if handle.url and _norm_url(handle.url) not in urls:
            urls.add(_norm_url(handle.url))
            _store.add_contact_point(
                conn,
                entity_id,
                "url",
                handle.url,
                service=handle.platform.strip().lower(),
                source=source,
            )
            added["urls"] += 1

    for im in contact.imClients:
        if not im.strip() or im.strip().lower() in ims:
            continue
        ims.add(im.strip().lower())
        _store.add_contact_point(
            conn, entity_id, "handle", im, service=IM_SERVICE, source=source
        )
        added["imClients"] += 1

    return {"entity_id": entity_id, "created": created, "added": added}


def contact_from_entity(conn: sqlite3.Connection, entity_id: int) -> StandardContact:
    """Reconstruct a ``StandardContact`` from a stored entity's contact points."""
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"no entity with id {entity_id}")

    google = conn.execute(
        "SELECT ref_value FROM external_refs WHERE entity_id = ? AND source = ?"
        " ORDER BY id DESC LIMIT 1",
        (entity_id, _GOOGLE_REF),
    ).fetchone()
    source_id = google["ref_value"] if google else f"{ENTITY_ID_PREFIX}{entity_id}"

    emails: list[str] = []
    phones: list[str] = []
    urls: list[str] = []
    handles: list[SocialHandle] = []
    ims: list[str] = []

    for point in conn.execute(
        "SELECT kind, value, service FROM contact_points WHERE entity_id = ?"
        " ORDER BY is_primary DESC, COALESCE(position, 0), id",
        (entity_id,),
    ):
        kind, value, service = point["kind"], point["value"], (point["service"] or "")
        if kind == "email":
            emails.append(value)
        elif kind == "phone":
            phones.append(value)
        elif kind == "url":
            urls.append(value)
        elif kind == "handle":
            if service == IM_SERVICE:
                ims.append(value)
            else:
                handles.append(
                    SocialHandle(platform=service or "unknown", username=value)
                )

    return StandardContact(
        source_id=source_id,
        display_name=row["display_name"] or "",
        handles=handles,
        emails=emails,
        phones=phones,
        urls=urls,
        imClients=ims,
    )
