import csv
from pathlib import Path
from collections.abc import Generator

from ..models import StandardContact
from ..interfaces import BaseAdapter


class GenericCSVAdapter(BaseAdapter):
    """Generic CSV fallback adapter for arbitrary contact data.

    Requires at minimum a ``Name`` or ``Display Name`` column
    (case-insensitive). Automatically maps known columns (Email, Phone,
    URL, IM) to the corresponding StandardContact fields. Any unrecognized
    columns are stored in ``raw_metadata``.
    """

    # Canonical field names mapped to their target attribute and type.
    _FIELD_MAP = {
        "email": ("emails", list),
        "phone": ("phones", list),
        "url": ("urls", list),
        "im": ("imClients", list),
    }

    def extract(self, file_path: Path) -> Generator[StandardContact, None, None]:
        """Extract contacts from a generic CSV file."""
        if not file_path.exists():
            return

        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                raise ValueError(
                    f"CSV file {file_path} appears to be empty or has no header row."
                )

            # Normalise header keys for case-insensitive matching
            norm_map = self._build_norm_map(reader.fieldnames)

            name_key = self._find_name_column(norm_map)
            if name_key is None:
                raise ValueError(
                    f"No name column found in {file_path}. "
                    f"Columns found: {', '.join(reader.fieldnames)}"
                )

            field_plan = self._plan_field_mapping(norm_map)

            for row in reader:
                row = {k.strip(): v.strip() for k, v in row.items()}

                display_name = row.get(name_key, "")
                if not display_name:
                    continue

                contact = StandardContact(
                    source_id=self._derive_source_id(row, field_plan, norm_map),
                    display_name=display_name,
                )

                # Map recognised fields
                for norm_key, (attr_name, _) in field_plan.get("mapped", {}).items():
                    value = row.get(norm_map[norm_key], "")
                    if value:
                        getattr(contact, attr_name).append(value)

                # Store unrecognised fields in raw_metadata
                for norm_key, original_key in field_plan.get("metadata", {}).items():
                    value = row.get(original_key, "")
                    if value:
                        contact.raw_metadata[original_key] = value

                yield contact

    def _build_norm_map(self, fieldnames: list[str]) -> dict[str, str]:
        """Build a mapping from lowercased header to original header."""
        return {key.strip().lower(): key.strip() for key in fieldnames}

    def _find_name_column(self, norm_map: dict[str, str]) -> str | None:
        """Find a name column (case-insensitive)."""
        for norm, original in norm_map.items():
            if "name" in norm:
                return original
        return None

    def _plan_field_mapping(
        self, norm_map: dict[str, str]
    ) -> dict:
        """Classify each column as mapped to a StandardContact field or raw metadata."""
        mapped: dict[str, tuple[str, type]] = {}
        metadata: dict[str, str] = {}

        for norm_key, original_key in norm_map.items():
            if self._is_name_column(norm_key):
                continue

            matched = False
            for canonical, (attr_name, _) in self._FIELD_MAP.items():
                if canonical in norm_key:
                    mapped[norm_key] = (attr_name, list)
                    matched = True
                    break

            if not matched:
                metadata[norm_key] = original_key

        return {"mapped": mapped, "metadata": metadata}

    @staticmethod
    def _is_name_column(norm_key: str) -> bool:
        return norm_key in ("name", "display name")

    @staticmethod
    def _derive_source_id(
        row: dict[str, str], field_plan: dict, norm_map: dict[str, str]
    ) -> str:
        """Derive a source_id from email if available, otherwise from display name."""
        mapped = field_plan.get("mapped", {})
        for norm_key, (attr_name, _) in mapped.items():
            if attr_name == "emails":
                email_value = row.get(norm_map[norm_key], "")
                if email_value:
                    return email_value

        # Fallback: use the name column
        for key, value in row.items():
            if "name" in key.lower() and value:
                return value.lower().replace(" ", "-")

        return "unknown"
