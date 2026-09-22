"""Tests for CLI module. Does NOT run the full reconciliation loop."""
from reconcile_core.main import fuzzy_match_name, ADAPTER_CLASSES
from reconcile_core.models import StandardContact


class TestFuzzyMatchName:
    def test_exact_match(self):
        contacts = [
            StandardContact(source_id="people/1", display_name="Alice Smith"),
            StandardContact(source_id="people/2", display_name="Bob Jones"),
        ]
        result = fuzzy_match_name("Alice Smith", contacts)
        assert result is not None
        assert result.source_id == "people/1"

    def test_close_match(self):
        contacts = [
            StandardContact(source_id="people/1", display_name="John Doe"),
            StandardContact(source_id="people/2", display_name="Jane Smith"),
        ]
        result = fuzzy_match_name("Jon Doe", contacts, threshold=0.85)
        assert result is not None
        assert result.source_id == "people/1"

    def test_no_match_below_threshold(self):
        contacts = [
            StandardContact(source_id="people/1", display_name="Alice Smith"),
        ]
        result = fuzzy_match_name("Bob Jones", contacts)
        assert result is None

    def test_empty_contacts_list(self):
        result = fuzzy_match_name("Alice Smith", [])
        assert result is None

    def test_case_insensitive(self):
        contacts = [
            StandardContact(source_id="people/1", display_name="Alice Smith"),
        ]
        result = fuzzy_match_name("alice smith", contacts)
        assert result is not None


class TestAdapterRegistry:
    def test_linkedin_available(self):
        assert "linkedin" in ADAPTER_CLASSES
        assert ADAPTER_CLASSES["linkedin"] is not None

    def test_discord_available(self):
        assert "discord" in ADAPTER_CLASSES
        assert ADAPTER_CLASSES["discord"] is not None

    def test_matrix_available(self):
        assert "matrix" in ADAPTER_CLASSES
        assert ADAPTER_CLASSES["matrix"] is not None

    def test_generic_available(self):
        assert "generic" in ADAPTER_CLASSES
        assert ADAPTER_CLASSES["generic"] is not None
