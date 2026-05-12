import pytest
from reconcile_core.google_adapter import GoogleAdapter, GWSCommandError


class TestParsePerson:
    def setup_method(self):
        self.adapter = GoogleAdapter()

    def test_empty_person(self):
        contact = self.adapter._parse_person({})
        assert contact.display_name == "Unnamed"
        assert contact.emails == []
        assert contact.phones == []

    def test_minimal_person(self):
        person = {
            "resourceName": "people/1",
            "etag": "abc",
            "names": [{"displayName": "Test User"}],
        }
        contact = self.adapter._parse_person(person)
        assert contact.source_id == "people/1"
        assert contact.display_name == "Test User"
        assert contact.raw_metadata["etag"] == "abc"

    def test_phones_extraction(self):
        person = {
            "resourceName": "people/1",
            "names": [{"displayName": "Phone User"}],
            "phoneNumbers": [
                {"value": "+1-555-0100"},
                {"value": "+1-555-0200"},
            ],
        }
        contact = self.adapter._parse_person(person)
        assert contact.phones == ["+1-555-0100", "+1-555-0200"]

    def test_phones_with_null_value(self):
        """Phone entries with no value should be skipped."""
        person = {
            "resourceName": "people/1",
            "names": [{"displayName": "Test"}],
            "phoneNumbers": [
                {"value": "+1-555-0100"},
                {"notValue": "ignored"},
            ],
        }
        contact = self.adapter._parse_person(person)
        assert contact.phones == ["+1-555-0100"]

    def test_all_fields(self):
        person = {
            "resourceName": "people/1",
            "etag": "abc",
            "names": [{"displayName": "Full Person"}],
            "emailAddresses": [{"value": "a@b.com"}, {"value": "c@d.com"}],
            "urls": [{"value": "https://alice.dev"}],
            "imClients": [{"username": "@alice:matrix.org"}],
            "phoneNumbers": [{"value": "+1-555-0300"}],
        }
        contact = self.adapter._parse_person(person)
        assert contact.emails == ["a@b.com", "c@d.com"]
        assert contact.urls == ["https://alice.dev"]
        assert contact.imClients == ["@alice:matrix.org"]
        assert contact.phones == ["+1-555-0300"]


class TestRunCommand:
    def test_binary_not_found(self):
        adapter = GoogleAdapter(gws_path="/nonexistent/gws")
        with pytest.raises(GWSCommandError, match="not found in PATH"):
            adapter._run_command(["list-connections"])
