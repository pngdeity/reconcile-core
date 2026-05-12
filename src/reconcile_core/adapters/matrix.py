import json
from pathlib import Path
from collections.abc import Generator

from ..models import StandardContact
from ..interfaces import BaseAdapter


class MatrixAdapter(BaseAdapter):
    """Adapter for Matrix/Element data exports.

    Supports two input formats:
    1. Element account data export containing an ``account_data`` array
       with ``m.direct`` entries mapping MXIDs to room IDs.
    2. A simple JSON list of objects with ``mxid`` and optional
       ``display_name`` keys.
    """

    def extract(self, file_path: Path) -> Generator[StandardContact, None, None]:
        """Extract contacts from a Matrix/Element export file."""
        if not file_path.exists():
            return

        with open(file_path, mode="r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Failed to parse Matrix JSON from {file_path}: {exc}"
                ) from exc

        # Try account_data / m.direct format first
        if isinstance(data, dict) and "account_data" in data:
            yield from self._extract_account_data(data, file_path)
        # Try simple list format
        elif isinstance(data, list):
            yield from self._extract_simple_list(data, file_path)
        else:
            raise ValueError(
                f"Unrecognized Matrix export format in {file_path}. "
                f"Expected an object with 'account_data' key or a JSON array."
            )

    def _extract_account_data(
        self, data: dict, file_path: Path
    ) -> Generator[StandardContact, None, None]:
        """Extract contacts from Element account_data with m.direct entries."""
        account_data = data.get("account_data", [])
        found_any = False

        for entry in account_data:
            entry_type = entry.get("type", "")
            if "m.direct" not in entry_type:
                continue

            content = entry.get("content", {})
            if not isinstance(content, dict):
                continue

            for mxid in content:
                if not mxid.startswith("@"):
                    continue
                found_any = True
                yield StandardContact(
                    source_id=mxid,
                    display_name=self._derive_display_name(mxid),
                    imClients=[mxid],
                )

        if not found_any:
            # m.direct format detected but no MXIDs extracted, try simple list
            yield from self._extract_simple_list(
                account_data, file_path
            )

    def _extract_simple_list(
        self, data: list, file_path: Path
    ) -> Generator[StandardContact, None, None]:
        """Extract contacts from a simple list of MXID objects."""
        for item in data:
            if not isinstance(item, dict):
                continue

            mxid = item.get("mxid", "")
            if not mxid:
                continue

            display_name = item.get("display_name") or self._derive_display_name(mxid)

            yield StandardContact(
                source_id=mxid,
                display_name=display_name,
                imClients=[mxid],
            )

    @staticmethod
    def _derive_display_name(mxid: str) -> str:
        """Derive a display name from an MXID by stripping '@' and the domain."""
        local = mxid.lstrip("@")
        if ":" in local:
            local = local.split(":")[0]
        return local
