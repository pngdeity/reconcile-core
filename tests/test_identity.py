"""Tests for store-side identity resolution (C2). Synthetic, no PII."""

import pytest

from reconcile_core import cli
from reconcile_core.store import (
    add_address,
    add_alias,
    add_contact_point,
    add_decision_state,
    add_external_ref,
    add_segment_member,
    apply_migrations,
    connect,
    create_entity,
    ensure_segment,
    find_duplicates,
    get_entity_by_ref,
    merge_entities,
    name_similarity,
    normalize_name,
    split_entity,
)


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "contacts.db"
    apply_migrations(db)
    connection = connect(db)
    yield connection
    connection.close()


def _person(conn, name, **fields):
    return create_entity(conn, type="person", display_name=name, **fields)


def _one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


# --- name matching (replaces the legacy fuzzy_match_name) --------------------


def test_normalize_name_strips_case_and_punctuation():
    assert normalize_name("Ada  Lovelace!") == "ada lovelace"


def test_name_similarity_exact_and_close():
    assert name_similarity("Ada Lovelace", "ada lovelace") == 1.0
    assert name_similarity("Jon Doe", "John Doe") > 0.75
    assert name_similarity("", "Ada") == 0.0


# --- duplicate detection -----------------------------------------------------


def test_find_duplicates_by_shared_email(conn):
    a = _person(conn, "Ada Lovelace")
    b = _person(conn, "Ada L")
    add_contact_point(conn, a, "email", "ada@example.com")
    add_contact_point(conn, b, "email", "ADA@example.com")

    found = find_duplicates(conn)
    assert len(found) == 1
    assert (found[0].entity_a, found[0].entity_b) == (min(a, b), max(a, b))
    assert "email" in found[0].shared
    assert found[0].score >= 0.5


def test_find_duplicates_by_shared_phone(conn):
    a = _person(conn, "Ada")
    b = _person(conn, "Grace")
    add_contact_point(conn, a, "phone", "+1 555 0100")
    add_contact_point(conn, b, "phone", "15550100")

    found = find_duplicates(conn)
    assert len(found) == 1
    assert "phone" in found[0].shared


def test_same_name_alone_is_below_default_threshold(conn):
    _person(conn, "Ada Lovelace")
    _person(conn, "Ada Lovelace")
    assert find_duplicates(conn) == []

    found = find_duplicates(conn, min_score=0.4)
    assert len(found) == 1
    assert found[0].shared == ()
    assert found[0].name_similarity == 1.0


def test_no_duplicates_for_distinct_entities(conn):
    a = _person(conn, "Ada Lovelace")
    b = _person(conn, "Grace Hopper")
    add_contact_point(conn, a, "email", "ada@example.com")
    add_contact_point(conn, b, "email", "grace@example.com")
    assert find_duplicates(conn) == []


# --- merge -------------------------------------------------------------------


def test_merge_is_lossless_and_dedupes(conn):
    src = _person(conn, "Ada Lovelace")
    dst = _person(conn, "Ada L")
    add_external_ref(conn, src, "linkedin", "ada")
    add_external_ref(conn, dst, "discord", "ada#1")
    src_email = add_contact_point(conn, src, "email", "ada@example.com")
    add_address(conn, src_email, city="Urbana")
    add_contact_point(conn, src, "phone", "+1 555 0100")
    add_contact_point(conn, dst, "email", "ADA@example.com")
    add_contact_point(conn, dst, "phone", "15550100")
    add_contact_point(conn, dst, "url", "https://ada.example")
    add_alias(conn, src, "name", "Ada L.")
    segment = ensure_segment(conn, "friends")
    add_segment_member(conn, segment, src)
    add_decision_state(conn, src, "invited")

    stats = merge_entities(conn, src, dst, reason="test")
    conn.commit()

    assert stats["refs"] == 1
    assert stats["contact_points"] == 2
    assert stats["duplicate_points"] == 2
    assert _one(conn, "SELECT COUNT(*) FROM entities WHERE id = ?", (src,)) == 0
    assert get_entity_by_ref(conn, "linkedin", "ada") == dst
    assert get_entity_by_ref(conn, "discord", "ada#1") == dst
    # Zero loss: the address moved with its contact point.
    assert _one(conn, "SELECT COUNT(*) FROM addresses") == 1
    assert (
        _one(
            conn,
            "SELECT COUNT(*) FROM segment_members WHERE entity_id = ?",
            (dst,),
        )
        == 1
    )
    assert (
        _one(conn, "SELECT COUNT(*) FROM decision_state WHERE entity_id = ?", (dst,))
        == 1
    )
    # Both the source's alias and its differing display name survive.
    assert _one(conn, "SELECT COUNT(*) FROM aliases WHERE entity_id = ?", (dst,)) == 2
    assert _one(conn, "SELECT COUNT(*) FROM audit_log WHERE action = 'MERGE'") == 1


def test_merge_adopts_name_when_target_is_nameless(conn):
    src = _person(conn, "Ada Lovelace")
    dst = _person(conn, "")
    merge_entities(conn, src, dst)
    conn.commit()
    assert _one(conn, "SELECT display_name FROM entities WHERE id = ?", (dst,)) == (
        "Ada Lovelace"
    )


def test_merge_rejects_self_and_missing(conn):
    entity = _person(conn, "Ada")
    with pytest.raises(ValueError):
        merge_entities(conn, entity, entity)
    with pytest.raises(ValueError):
        merge_entities(conn, entity, 999999)


# --- split -------------------------------------------------------------------


def test_split_moves_selected_refs_and_points(conn):
    entity = _person(conn, "Ada Lovelace", first_name="Ada")
    add_external_ref(conn, entity, "linkedin", "ada")
    add_external_ref(conn, entity, "discord", "ada#1")
    email = add_contact_point(conn, entity, "email", "ada@example.com")
    phone = add_contact_point(conn, entity, "phone", "+1 555 0100")
    conn.commit()

    new_id = split_entity(
        conn,
        entity,
        refs=[("discord", "ada#1")],
        contact_point_ids=[phone],
        display_name="Ada D",
    )
    conn.commit()

    assert get_entity_by_ref(conn, "discord", "ada#1") == new_id
    assert get_entity_by_ref(conn, "linkedin", "ada") == entity
    assert (
        _one(conn, "SELECT entity_id FROM contact_points WHERE id = ?", (phone,))
        == new_id
    )
    assert (
        _one(conn, "SELECT entity_id FROM contact_points WHERE id = ?", (email,))
        == entity
    )
    assert _one(conn, "SELECT COUNT(*) FROM audit_log WHERE action = 'SPLIT'") == 1


def test_split_rejects_unknown_ref(conn):
    entity = _person(conn, "Ada")
    conn.commit()
    with pytest.raises(ValueError):
        split_entity(conn, entity, refs=[("linkedin", "nope")])


def test_split_rejects_empty_request(conn):
    entity = _person(conn, "Ada")
    with pytest.raises(ValueError):
        split_entity(conn, entity)


# --- CLI surface -------------------------------------------------------------


def test_cli_duplicates_lists_candidates(tmp_path, capsys):
    db = tmp_path / "c.db"
    apply_migrations(db)
    conn = connect(db)
    a = create_entity(conn, type="person", display_name="Ada Lovelace")
    b = create_entity(conn, type="person", display_name="Ada L")
    add_contact_point(conn, a, "email", "ada@example.com")
    add_contact_point(conn, b, "email", "ada@example.com")
    conn.commit()
    conn.close()

    assert cli.main(["duplicates", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert str(a) in out and str(b) in out
    assert "email" in out


def test_cli_merge_folds_entities(tmp_path, capsys):
    db = tmp_path / "c.db"
    apply_migrations(db)
    conn = connect(db)
    src = create_entity(conn, type="person", display_name="Ada Lovelace")
    dst = create_entity(conn, type="person", display_name="Ada L")
    add_external_ref(conn, src, "linkedin", "ada")
    conn.commit()
    conn.close()

    assert cli.main(["merge", str(src), str(dst), "--db", str(db)]) == 0
    capsys.readouterr()

    conn = connect(db)
    assert get_entity_by_ref(conn, "linkedin", "ada") == dst
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1
    conn.close()


def test_cli_split_creates_entity(tmp_path, capsys):
    db = tmp_path / "c.db"
    apply_migrations(db)
    conn = connect(db)
    entity = create_entity(conn, type="person", display_name="Ada Lovelace")
    add_external_ref(conn, entity, "discord", "ada#1")
    conn.commit()
    conn.close()

    assert (
        cli.main(["split", str(entity), "--ref", "discord:ada#1", "--db", str(db)]) == 0
    )
    capsys.readouterr()

    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 2
    conn.close()
