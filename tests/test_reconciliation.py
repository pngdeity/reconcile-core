from reconcile_core.models import SocialHandle, StandardContact
from reconcile_core.reconciler import Reconciler


def test_reconciliation_normalization():
    reconciler = Reconciler()
    # Proposed has uppercase email and URL with trailing slash
    proposed = StandardContact(
        source_id="p1",
        display_name="John Doe",
        emails=["EMAIL@EXAMPLE.COM"],
        urls=["https://linkedin.com/in/johndoe/"],
    )
    # Current has lowercase and no trailing slash
    current = StandardContact(
        source_id="people/1",
        display_name="John Doe",
        emails=["email@example.com"],
        urls=["https://linkedin.com/in/johndoe"],
    )

    diff = reconciler.reconcile(proposed, current)

    # Should result in NO additions due to normalization
    assert len(diff.additions.emails) == 0
    assert len(diff.additions.urls) == 0


def test_reconciliation_new_data():
    reconciler = Reconciler()
    proposed = StandardContact(
        source_id="p1", display_name="John Doe", emails=["new@example.com"]
    )
    current = StandardContact(
        source_id="people/1", display_name="John Doe", emails=["old@example.com"]
    )

    diff = reconciler.reconcile(proposed, current)

    assert len(diff.additions.emails) == 1
    assert diff.additions.emails[0] == "new@example.com"


def test_phones_union_normalization():
    """Phone numbers that differ only in formatting should be treated as duplicates."""
    reconciler = Reconciler()
    proposed = StandardContact(
        source_id="p1", display_name="John", phones=["+1-555-0100", "+1 (555) 0200"]
    )
    current = StandardContact(
        source_id="people/1",
        display_name="John",
        phones=["+1 (555) 0100"],  # same as first, formatted differently
    )
    diff = reconciler.reconcile(proposed, current)
    assert diff.additions.phones == ["+1 (555) 0200"]


def test_phones_all_existing():
    """No additions when all phones already exist."""
    reconciler = Reconciler()
    proposed = StandardContact(
        source_id="p1", display_name="Jane", phones=["+1 555-0100"]
    )
    current = StandardContact(
        source_id="people/1", display_name="Jane", phones=["+1-555-0100"]
    )
    diff = reconciler.reconcile(proposed, current)
    assert len(diff.additions.phones) == 0


def test_display_name_collision():
    """Name mismatch should produce collision, additions.display_name should be empty."""
    reconciler = Reconciler()
    proposed = StandardContact(source_id="p1", display_name="Alice Smith")
    current = StandardContact(source_id="people/1", display_name="Alice Jones")
    diff = reconciler.reconcile(proposed, current)
    assert "display_name" in diff.collisions
    assert diff.collisions["display_name"] == ("Alice Jones", "Alice Smith")
    assert diff.additions.display_name == ""


def test_no_changes():
    """Identical contacts should produce no additions and no collisions."""
    reconciler = Reconciler()
    c = StandardContact(
        source_id="p1", display_name="Bob", emails=["bob@test.com"], phones=["555-0100"]
    )
    current = StandardContact(
        source_id="people/1",
        display_name="Bob",
        emails=["bob@test.com"],
        phones=["555-0100"],
    )
    diff = reconciler.reconcile(c, current)
    assert len(diff.additions.emails) == 0
    assert len(diff.additions.phones) == 0
    assert len(diff.additions.urls) == 0
    assert len(diff.additions.imClients) == 0
    assert diff.collisions == {}


def test_handles_union_normalized():
    """Handles are unioned by (platform, username), case-insensitively."""
    reconciler = Reconciler()
    proposed = StandardContact(
        source_id="p1",
        display_name="Jane Doe",
        handles=[
            SocialHandle(platform="GitHub", username="JaneDoe"),
            SocialHandle(platform="x", username="janedoe"),
        ],
    )
    current = StandardContact(
        source_id="people/1",
        display_name="Jane Doe",
        handles=[SocialHandle(platform="github", username="janedoe")],
    )

    diff = reconciler.reconcile(proposed, current)

    assert [(h.platform, h.username) for h in diff.additions.handles] == [
        ("x", "janedoe")
    ]


def test_handles_no_changes():
    """Matching handles produce no handle additions."""
    reconciler = Reconciler()
    proposed = StandardContact(
        source_id="p1",
        display_name="Jane",
        handles=[SocialHandle(platform="github", username="janedoe")],
    )
    current = StandardContact(
        source_id="people/1",
        display_name="Jane",
        handles=[SocialHandle(platform="github", username="janedoe")],
    )

    diff = reconciler.reconcile(proposed, current)

    assert diff.additions.handles == []
