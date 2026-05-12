from abc import ABC, abstractmethod
from collections.abc import Generator
from pathlib import Path

from .models import StandardContact


class BaseAdapter(ABC):
    @abstractmethod
    def extract(self, file_path: Path) -> Generator[StandardContact, None, None]:
        """Extract contacts from a platform-specific data file."""
        pass


class BasePersistence(ABC):
    @abstractmethod
    def get_resource_name(self, platform: str, source_id: str) -> str | None:
        """Retrieve the Google resourceName for a given platform identity."""
        pass

    @abstractmethod
    def set_mapping(self, platform: str, source_id: str, resource_name: str) -> None:
        """Store the mapping between a platform identity and a Google resourceName."""
        pass

    @abstractmethod
    def list_unresolved(self) -> list[tuple[str, str]]:
        """List all platform identities that haven't been resolved to a Google contact."""
        pass
