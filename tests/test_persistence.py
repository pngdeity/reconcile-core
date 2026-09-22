import pytest
from reconcile_core.database import SQLitePersistence


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test.db"
    return db_file


def test_db_initialization(temp_db):
    db = SQLitePersistence(temp_db)
    assert temp_db.exists()

    with db._connection() as conn:
        entities = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entities'"
        ).fetchone()
        refs = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='external_refs'"
        ).fetchone()
        assert entities is not None
        assert refs is not None


def test_set_and_get_mapping(temp_db):
    db = SQLitePersistence(temp_db)
    db.set_mapping("linkedin", "nathan-slug", "people/12345")

    res = db.get_resource_name("linkedin", "nathan-slug")
    assert res == "people/12345"


def test_idempotency_set_mapping(temp_db):
    db = SQLitePersistence(temp_db)
    db.set_mapping("linkedin", "nathan-slug", "people/12345")
    # Setting it again with same or different resource name should work
    db.set_mapping("linkedin", "nathan-slug", "people/67890")

    res = db.get_resource_name("linkedin", "nathan-slug")
    assert res == "people/67890"


def test_audit_logging(temp_db):
    db = SQLitePersistence(temp_db)
    db.log_audit("people/12345", "UPDATE", "Added email")

    with db._connection() as conn:
        cursor = conn.execute(
            "SELECT action FROM audit_log WHERE resource_name = ?", ("people/12345",)
        )
        assert cursor.fetchone()[0] == "UPDATE"


def test_shared_resource_converges_on_one_entity(temp_db):
    db = SQLitePersistence(temp_db)
    db.set_mapping("linkedin", "nathan-slug", "people/12345")
    db.set_mapping("discord", "1234567890", "people/12345")

    with db._connection() as conn:
        entity_ids = {
            row[0]
            for row in conn.execute(
                "SELECT entity_id FROM external_refs WHERE source IN ('linkedin', 'discord')"
            )
        }
    assert len(entity_ids) == 1
    assert db.get_resource_name("linkedin", "nathan-slug") == "people/12345"
    assert db.get_resource_name("discord", "1234567890") == "people/12345"
