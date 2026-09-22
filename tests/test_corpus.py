"""Golden regression harness over a synthetic, no-PII corpus (C4, ADR-0004).

The corpus in ``test_data/corpus/`` is the shared fixture the rest of the
Tier 2 work (C2/C3/C5) builds on. It exercises the P1 pipeline end to end:

- multi-platform ingestion through the real adapters,
- identity convergence via a shared email (plus case-insensitive matching),
- zero-loss union and idempotency,
- display-name collisions surfaced but never auto-applied,
- the Google Contacts projection round-tripping cell for cell.

Regenerate the store golden after an intentional change:

    UPDATE_CORPUS_GOLDEN=1 uv run pytest tests/test_corpus.py -k matches_golden
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from reconcile_core.adapters.discord import DiscordAdapter
from reconcile_core.adapters.generic_csv import GenericCSVAdapter
from reconcile_core.adapters.linkedin import LinkedInAdapter
from reconcile_core.adapters.matrix import MatrixAdapter
from reconcile_core.database import SQLitePersistence
from reconcile_core.io import google_csv
from reconcile_core.models import StandardContact
from reconcile_core.reconciler import Reconciler
from reconcile_core.store import connect, contact_from_entity, counts, get_entity_by_ref
from reconcile_core.store.bridge import write_contact

CORPUS = Path(__file__).resolve().parents[1] / "test_data" / "corpus"
GOLDEN = CORPUS / "store_golden.json"

# Order is fixed: primary-email selection depends on insertion order.
SOCIAL_SOURCES = (
    ("linkedin", LinkedInAdapter, "linkedin.csv"),
    ("generic", GenericCSVAdapter, "generic.csv"),
    ("discord", DiscordAdapter, "discord.json"),
    ("matrix", MatrixAdapter, "matrix.json"),
)


def ingest_social(db_path) -> dict:
    """Ingest the social corpus and aggregate the bridge stats."""
    persistence = SQLitePersistence(db_path)
    total = created = 0
    added: Counter[str] = Counter()
    for platform, adapter_cls, filename in SOCIAL_SOURCES:
        for contact in adapter_cls().extract(CORPUS / filename):
            stats = persistence.ingest(
                contact, platform=platform, source_id=contact.source_id
            )
            total += 1
            created += int(stats["created"])
            added.update(stats["added"])
    return {"total": total, "created": created, "added": dict(added)}


def store_projection(conn) -> dict:
    """A deterministic, order-stable description of the whole store."""
    entities = []
    for row in conn.execute("SELECT id, display_name, type FROM entities"):
        refs = sorted(
            [r["source"], r["ref_value"]]
            for r in conn.execute(
                "SELECT source, ref_value FROM external_refs WHERE entity_id = ?",
                (row["id"],),
            )
        )
        points = sorted(
            [p["kind"], p["value"], p["service"] or ""]
            for p in conn.execute(
                "SELECT kind, value, service FROM contact_points WHERE entity_id = ?",
                (row["id"],),
            )
        )
        entities.append(
            {
                "display_name": row["display_name"] or "",
                "type": row["type"],
                "refs": refs,
                "points": points,
            }
        )
    entities.sort(key=lambda e: (e["refs"], e["display_name"], e["type"]))
    return {"counts": counts(conn), "entities": entities}


def _refs(conn, entity_id: int) -> set[tuple[str, str]]:
    return {
        (r["source"], r["ref_value"])
        for r in conn.execute(
            "SELECT source, ref_value FROM external_refs WHERE entity_id = ?",
            (entity_id,),
        )
    }


def _points(conn, entity_id: int) -> set[tuple[str, str, str]]:
    return {
        (r["kind"], r["value"], r["service"] or "")
        for r in conn.execute(
            "SELECT kind, value, service FROM contact_points WHERE entity_id = ?",
            (entity_id,),
        )
    }


@pytest.fixture
def social_db(tmp_path):
    db = tmp_path / "corpus.db"
    ingest_social(db)
    return db


@pytest.fixture
def social_conn(social_db):
    conn = connect(social_db)
    yield conn
    conn.close()


def test_social_corpus_store_matches_golden(social_conn):
    projection = store_projection(social_conn)
    if os.environ.get("UPDATE_CORPUS_GOLDEN"):
        GOLDEN.write_text(
            json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert projection == expected


def test_social_corpus_is_idempotent(tmp_path):
    db = tmp_path / "idempotent.db"
    first = ingest_social(db)
    second = ingest_social(db)
    assert first["created"] > 0
    assert second["created"] == 0
    assert sum(second["added"].values()) == 0


def test_shared_email_converges_across_platforms(social_conn):
    ada = get_entity_by_ref(social_conn, "linkedin", "ada-lovelace")
    assert ada is not None
    assert _refs(social_conn, ada) == {
        ("linkedin", "ada-lovelace"),
        ("generic", "ada@example.com"),
    }
    assert _points(social_conn, ada) >= {
        ("email", "ada@example.com", ""),
        ("phone", "+1-555-0100", ""),
        ("url", "https://www.linkedin.com/in/ada-lovelace", ""),
        ("url", "https://ada.example", ""),
        ("handle", "@ada:chat.example", "im"),
    }


def test_email_convergence_is_case_insensitive(social_conn):
    grace = get_entity_by_ref(social_conn, "linkedin", "grace-hopper")
    assert grace is not None
    assert _refs(social_conn, grace) == {
        ("linkedin", "grace-hopper"),
        ("generic", "GRACE@EXAMPLE.COM"),
    }
    emails = [p for p in _points(social_conn, grace) if p[0] == "email"]
    assert emails == [("email", "grace@example.com", "")]


def test_non_converging_platforms_stay_separate(social_conn):
    # Without a shared email, handle-only platforms remain their own entities.
    nadia = get_entity_by_ref(social_conn, "matrix", "@nadia:matrix.example")
    omar = get_entity_by_ref(social_conn, "matrix", "@omar:matrix.example")
    assert nadia is not None and omar is not None and nadia != omar
    assert _points(social_conn, nadia) == {("handle", "@nadia:matrix.example", "im")}
    discord = get_entity_by_ref(social_conn, "discord", "100000000000000002")
    assert _points(social_conn, discord) == {("handle", "grace.h#1234", "discord")}


def test_blocked_discord_relationships_are_excluded(social_conn):
    assert get_entity_by_ref(social_conn, "discord", "100000000000000003") is None
    handle_values = {
        row["value"] for row in social_conn.execute("SELECT value FROM contact_points")
    }
    assert "blocked.user" not in handle_values


def test_reconcile_surfaces_name_collision_without_overwriting(social_conn):
    entity_id = get_entity_by_ref(social_conn, "linkedin", "ada-lovelace")
    current = contact_from_entity(social_conn, entity_id)
    proposed = StandardContact(
        source_id="ada-lovelace",
        display_name="Ada B. Lovelace",
        emails=["ada2@example.com"],
    )

    diff = Reconciler().reconcile(proposed, current)

    assert diff.collisions["display_name"] == ("Ada Lovelace", "Ada B. Lovelace")
    assert diff.additions.emails == ["ada2@example.com"]

    write_contact(social_conn, diff.additions, entity_id=entity_id, source="reconcile")
    merged = contact_from_entity(social_conn, entity_id)
    assert merged.display_name == "Ada Lovelace"  # collision not applied
    assert "ada2@example.com" in merged.emails


def test_google_projection_round_trips_corpus(tmp_path):
    rows = json.loads((CORPUS / "google_contacts.json").read_text(encoding="utf-8"))
    sample = tmp_path / "Contacts.csv"
    with open(sample, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=google_csv.HEADER, quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        writer.writerows(rows)

    db = tmp_path / "google.db"
    google_csv.import_contacts(sample, db)
    out = tmp_path / "out"
    google_csv.export_contacts(out, db)

    with open(out / "Contacts.csv", newline="", encoding="utf-8") as f:
        exported = {r["ID"]: r for r in csv.DictReader(f)}

    expected = {r["ID"]: r for r in rows}
    assert set(exported) == set(expected)
    for cid, spec in expected.items():
        for column, value in spec.items():
            assert exported[cid][column] == value, f"ID {cid} column {column!r}"
        for column in google_csv.HEADER:
            if column not in spec:
                assert exported[cid][column] == "", f"ID {cid} column {column!r}"
