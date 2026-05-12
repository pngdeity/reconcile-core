import pytest
from reconcile_core.models import StandardContact, SocialHandle
from reconcile_core.interfaces import BaseAdapter, BasePersistence

def test_standard_contact_defaults():
    contact = StandardContact(source_id="123", display_name="John Doe")
    assert contact.source_id == "123"
    assert contact.display_name == "John Doe"
    assert isinstance(contact.handles, list)
    assert len(contact.handles) == 0
    assert isinstance(contact.emails, list)
    assert isinstance(contact.phones, list)
    assert isinstance(contact.urls, list)
    assert isinstance(contact.imClients, list)
    assert isinstance(contact.raw_metadata, dict)

def test_social_handle_defaults():
    handle = SocialHandle(platform="linkedin", username="johndoe")
    assert handle.platform == "linkedin"
    assert handle.username == "johndoe"
    assert handle.url is None
    assert handle.is_im is False

def test_base_adapter_is_abstract():
    with pytest.raises(TypeError) as excinfo:
        BaseAdapter()
    assert "Can't instantiate abstract class BaseAdapter" in str(excinfo.value)

def test_base_persistence_is_abstract():
    with pytest.raises(TypeError) as excinfo:
        BasePersistence()
    assert "Can't instantiate abstract class BasePersistence" in str(excinfo.value)
