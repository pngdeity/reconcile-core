"""Tests for the StandardContact <-> store bridge (B3). Synthetic, no PII."""

import pytest

from reconcile_core.models import SocialHandle, StandardContact
from reconcile_core.reconciler import Reconciler
from reconcile_core.store import apply_migrations, connect, counts, get_entity_by_ref
from reconcile_core.store.bridge import (
    contact_from_entity,
    find_entity_by_email,
    write_contact,
)


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    connection = connect(db)
    yield connection
    connection.close()


def _contact(**kwargs) -> StandardContact:
    data = {"source_id": "p1", "display_name": "Jane Doe"}
    data.update(kwargs)
    return StandardContact(**data)


def test_write_creates_entity_and_points(conn):
    result = write_contact(
        conn,
        _contact(
            emails=["jane@example.com", "j.doe@work.example"],
            phones=["+1 555 0100"],
            urls=["https://example.com/jane"],
            handles=[
                SocialHandle(platform="LinkedIn", username="jane-doe"),
                SocialHandle(
                    platform="github",
                    username="janedoe",
                    url="https://github.com/janedoe",
                ),
            ],
            imClients=["janedoe"],
        ),
    )

    assert result["created"] is True
    assert result["added"] == {
        "emails": 2,
        "phones": 1,
        "urls": 2,  # the profile URL plus the handle's URL
        "handles": 2,
        "imClients": 1,
    }
    assert counts(conn)["entities"] == 1
    assert counts(conn)["contact_points"] == 8

    primary = conn.execute(
        "SELECT value FROM contact_points WHERE kind = 'email' AND is_primary = 1"
    ).fetchall()
    assert [row["value"] for row in primary] == ["jane@example.com"]


def test_write_is_idempotent(conn):
    contact = _contact(
        emails=["jane@example.com"],
        phones=["+1 555 0100"],
        handles=[SocialHandle("github", "janedoe")],
    )
    first = write_contact(conn, contact)
    second = write_contact(conn, contact)

    assert first["created"] is True
    assert second["created"] is False
    assert first["entity_id"] == second["entity_id"]
    assert second["added"] == {
        "emails": 0,
        "phones": 0,
        "urls": 0,
        "handles": 0,
        "imClients": 0,
    }
    assert counts(conn)["entities"] == 1


def test_two_identities_same_email_converge(conn):
    a = write_contact(
        conn, _contact(emails=["Jane@Example.com"]), platform="linkedin", source_id="a"
    )
    b = write_contact(
        conn,
        _contact(emails=["jane@example.com"], phones=["+1 555 0200"]),
        platform="linkedin",
        source_id="b",
    )

    assert a["created"] is True
    assert b["created"] is False
    assert a["entity_id"] == b["entity_id"]
    assert b["added"]["phones"] == 1
    assert get_entity_by_ref(conn, "linkedin", "a") == a["entity_id"]
    assert get_entity_by_ref(conn, "linkedin", "b") == a["entity_id"]


def test_round_trip(conn):
    contact = _contact(
        emails=["jane@example.com"],
        phones=["+1 555 0100"],
        urls=["https://x.example/"],
        handles=[SocialHandle("github", "janedoe")],
        imClients=["jane-im"],
    )
    result = write_contact(conn, contact)
    back = contact_from_entity(conn, result["entity_id"])

    assert back.display_name == "Jane Doe"
    assert back.emails == ["jane@example.com"]
    assert back.phones == ["+1 555 0100"]
    assert back.urls == ["https://x.example/"]
    assert [(h.platform, h.username) for h in back.handles] == [("github", "janedoe")]
    assert back.imClients == ["jane-im"]


def test_find_entity_by_email_normalizes(conn):
    result = write_contact(conn, _contact(emails=["Mixed.Case@Example.com"]))
    assert find_entity_by_email(conn, "mixed.case@example.com") == result["entity_id"]
    assert find_entity_by_email(conn, "nobody@example.com") is None


def test_reconcile_against_store_record_includes_handles(conn):
    result = write_contact(
        conn,
        _contact(
            emails=["jane@example.com"], handles=[SocialHandle("github", "janedoe")]
        ),
    )
    current = contact_from_entity(conn, result["entity_id"])
    proposed = _contact(
        emails=["jane@example.com", "new@example.com"],
        handles=[
            SocialHandle("GitHub", "JaneDoe"),  # duplicate after normalization
            SocialHandle("x", "janedoe"),
        ],
    )

    diff = Reconciler().reconcile(proposed, current)

    assert diff.additions.emails == ["new@example.com"]
    assert [(h.platform, h.username) for h in diff.additions.handles] == [
        ("x", "janedoe")
    ]
