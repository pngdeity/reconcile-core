import json
import pytest
from pathlib import Path
from reconcile_core.adapters.linkedin import LinkedInAdapter
from reconcile_core.adapters.discord import DiscordAdapter
from reconcile_core.adapters.matrix import MatrixAdapter
from reconcile_core.adapters.generic_csv import GenericCSVAdapter


# --- LinkedIn ---

def test_linkedin_extracts_emails_and_metadata(tmp_path):
    csv_path = tmp_path / "test.csv"
    csv_path.write_text(
        "First Name,Last Name,Email Address,Company,Position,URL\n"
        "John,Doe,john@test.com,Acme,Engineer,https://linkedin.com/in/john-doe\n"
        "Jane,Smith,,,,https://linkedin.com/in/jane-smith\n"
    )
    adapter = LinkedInAdapter()
    contacts = list(adapter.extract(csv_path))
    assert len(contacts) == 2
    assert contacts[0].emails == ["john@test.com"]
    assert contacts[0].raw_metadata == {"company": "Acme", "position": "Engineer"}
    assert contacts[1].emails == []
    assert contacts[1].raw_metadata == {}


def test_linkedin_missing_header_raises(tmp_path):
    csv_path = tmp_path / "no_header.csv"
    csv_path.write_text("Noise,line,here\nSome,data,too\n")
    adapter = LinkedInAdapter()
    with pytest.raises(ValueError, match="First Name"):
        list(adapter.extract(csv_path))


def test_linkedin_skips_empty_rows(tmp_path):
    csv_path = tmp_path / "test.csv"
    csv_path.write_text(
        "First Name,Last Name,URL\n"
        "Alice,Smith,https://linkedin.com/in/alice\n"
        ",,\n"
    )
    adapter = LinkedInAdapter()
    contacts = list(adapter.extract(csv_path))
    assert len(contacts) == 1
    assert contacts[0].display_name == "Alice Smith"


def test_linkedin_missing_file(tmp_path):
    adapter = LinkedInAdapter()
    contacts = list(adapter.extract(Path("/nonexistent/file.csv")))
    assert contacts == []


# --- Discord ---

def test_discord_extracts_friends_only(tmp_path):
    data = [
        {"id": "1", "type": 1, "user": {"username": "friend1", "discriminator": "1234", "id": "111"}},
        {"id": "2", "type": 2, "user": {"username": "blocked", "discriminator": "0", "id": "222"}},
        {"id": "3", "type": 1, "user": {"username": "friend2", "discriminator": "5678", "id": "333"}},
    ]
    json_path = tmp_path / "relationships.json"
    json_path.write_text(json.dumps(data))
    adapter = DiscordAdapter()
    contacts = list(adapter.extract(json_path))
    assert len(contacts) == 2
    assert contacts[0].display_name == "friend1#1234"
    assert contacts[1].display_name == "friend2#5678"
    assert contacts[0].source_id == "111"


def test_discord_missing_file(tmp_path):
    adapter = DiscordAdapter()
    contacts = list(adapter.extract(Path("/nonexistent/rel.json")))
    assert contacts == []


def test_discord_malformed_json_returns_empty(tmp_path):
    json_path = tmp_path / "bad.json"
    json_path.write_text("this is not json")
    adapter = DiscordAdapter()
    contacts = list(adapter.extract(json_path))
    assert contacts == []


# --- Matrix ---

def test_matrix_simple_list_format(tmp_path):
    data = [
        {"mxid": "@alice:matrix.org", "display_name": "Alice"},
        {"mxid": "@bob:matrix.org"},
    ]
    json_path = tmp_path / "matrix.json"
    json_path.write_text(json.dumps(data))
    adapter = MatrixAdapter()
    contacts = list(adapter.extract(json_path))
    assert len(contacts) == 2
    assert contacts[0].display_name == "Alice"
    assert contacts[0].imClients == ["@alice:matrix.org"]
    assert contacts[1].display_name == "bob"
    assert contacts[1].imClients == ["@bob:matrix.org"]


def test_matrix_account_data_format(tmp_path):
    data = {
        "account_data": [
            {
                "type": "m.direct",
                "content": {
                    "@alice:matrix.org": ["!room1:matrix.org"],
                    "@bob:matrix.org": ["!room2:matrix.org"],
                }
            }
        ]
    }
    json_path = tmp_path / "matrix.json"
    json_path.write_text(json.dumps(data))
    adapter = MatrixAdapter()
    contacts = list(adapter.extract(json_path))
    assert len(contacts) == 2
    mxids = {c.source_id for c in contacts}
    assert "@alice:matrix.org" in mxids
    assert "@bob:matrix.org" in mxids


def test_matrix_missing_file(tmp_path):
    adapter = MatrixAdapter()
    contacts = list(adapter.extract(Path("/nonexistent/m.json")))
    assert contacts == []


# --- Generic CSV ---

def test_generic_csv_all_fields(tmp_path):
    csv_path = tmp_path / "test.csv"
    csv_path.write_text(
        "Name,Email,Phone,URL,IM,Company\n"
        "Alice,alice@test.com,+1-555-0100,https://alice.dev,@alice:matrix.org,Acme\n"
    )
    adapter = GenericCSVAdapter()
    contacts = list(adapter.extract(csv_path))
    assert len(contacts) == 1
    c = contacts[0]
    assert c.display_name == "Alice"
    assert c.emails == ["alice@test.com"]
    assert c.phones == ["+1-555-0100"]
    assert c.urls == ["https://alice.dev"]
    assert c.imClients == ["@alice:matrix.org"]
    assert c.raw_metadata["Company"] == "Acme"


def test_generic_csv_no_name_column_raises(tmp_path):
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("Email,Phone\njohn@test.com,555\n")
    adapter = GenericCSVAdapter()
    with pytest.raises(ValueError, match="[Nn]ame"):
        list(adapter.extract(csv_path))


def test_generic_csv_derives_source_id(tmp_path):
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("Name,Email\nBob,bob@test.com\n")
    adapter = GenericCSVAdapter()
    contacts = list(adapter.extract(csv_path))
    assert len(contacts) == 1
    assert contacts[0].source_id == "bob@test.com"


def test_generic_csv_missing_file(tmp_path):
    adapter = GenericCSVAdapter()
    contacts = list(adapter.extract(Path("/nonexistent/file.csv")))
    assert contacts == []


def test_generic_csv_skips_empty_rows(tmp_path):
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("Name,Email\nAlice,a@b.com\n,\n")
    adapter = GenericCSVAdapter()
    contacts = list(adapter.extract(csv_path))
    assert len(contacts) == 1
