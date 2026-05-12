import csv
from pathlib import Path
from collections.abc import Generator
from ..models import StandardContact
from ..interfaces import BaseAdapter

class LinkedInAdapter(BaseAdapter):
    def extract(self, file_path: Path) -> Generator[StandardContact, None, None]:
        """Extract contacts from LinkedIn Connections.csv.

        Parses the standard LinkedIn data export CSV. Extracts:
        - First Name, Last Name → display_name
        - URL → source_id (slug) and urls list
        - Email Address → emails list
        - Company, Position → raw_metadata dict

        Raises ValueError if the expected header row (containing "First Name")
        cannot be located.
        """
        if not file_path.exists():
            return

        with open(file_path, mode='r', encoding='utf-8') as f:
            lines = f.readlines()

        start_idx = 0
        for i, line in enumerate(lines):
            if "First Name" in line:
                start_idx = i
                break

        if start_idx == 0 and (not lines or "First Name" not in lines[0]):
            raise ValueError("Could not find LinkedIn CSV header row with 'First Name' column.")

        reader = csv.DictReader(lines[start_idx:])

        for row in reader:
            first_name = row.get("First Name", "").strip()
            last_name = row.get("Last Name", "").strip()
            url = row.get("URL", "").strip()

            if not first_name and not last_name:
                continue

            display_name = f"{first_name} {last_name}".strip()

            # Generate source_id from profile slug
            # e.g., https://www.linkedin.com/in/nathan-somers -> nathan-somers
            source_id = url.rstrip('/').split('/')[-1] if url else display_name.lower().replace(" ", "-")

            email = row.get("Email Address", "").strip()
            emails = [email] if email else []

            company = row.get("Company", "").strip()
            position = row.get("Position", "").strip()
            raw_metadata: dict[str, str] = {}
            if company:
                raw_metadata["company"] = company
            if position:
                raw_metadata["position"] = position

            yield StandardContact(
                source_id=source_id,
                display_name=display_name,
                urls=[url] if url else [],
                emails=emails,
                raw_metadata=raw_metadata,
            )
