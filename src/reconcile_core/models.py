from dataclasses import dataclass, field
from typing import Any


@dataclass
class SocialHandle:
    platform: str
    username: str
    url: str | None = None
    is_im: bool = False


@dataclass
class StandardContact:
    source_id: str
    display_name: str
    handles: list[SocialHandle] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    imClients: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReconciliationDiff:
    resource_name: str
    additions: StandardContact
    collisions: dict[str, tuple[Any, Any]] = field(default_factory=dict)
