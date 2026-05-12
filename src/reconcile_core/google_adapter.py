import json
import logging
import subprocess
import time
from typing import Any, Optional
from .models import StandardContact, SocialHandle

logger = logging.getLogger(__name__)

class GWSCommandError(Exception):
    """Raised when a gws command fails."""
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr

class GoogleAdapter:
    def __init__(self, gws_path: str = "gws"):
        self.gws_path = gws_path
        self._cache: dict[str, StandardContact] = {}

    def _run_command(self, args: list[str]) -> str:
        """Execute a gws command and return stdout, with exponential backoff on rate limits."""
        cmd = [self.gws_path] + args
        max_retries = 5
        base_delay = 1

        for attempt in range(max_retries + 1):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                return result.stdout
            except subprocess.CalledProcessError as e:
                stderr_lower = e.stderr.lower() if e.stderr else ""
                is_rate_limit = "429" in e.stderr or "resource_exhausted" in stderr_lower
                if is_rate_limit and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Rate limit hit on attempt %d/%d. Retrying in %ds...",
                        attempt + 1, max_retries + 1, delay
                    )
                    time.sleep(delay)
                else:
                    raise GWSCommandError(
                        f"Command '{' '.join(cmd)}' failed with exit code {e.returncode}", e.stderr
                    ) from e
            except FileNotFoundError:
                raise GWSCommandError(f"Binary '{self.gws_path}' not found in PATH.")

    def fetch_all_contacts(self, page_size: int = 100) -> list[StandardContact]:
        """Fetch all connections from Google Contacts with pagination support."""
        contacts = []
        page_token = None
        
        while True:
            args = [
                "people", "list-connections", 
                "--read-mask", "names,emailAddresses,urls,imClients,phoneNumbers",
                "--page-size", str(page_size)
            ]
            if page_token:
                args.extend(["--page-token", page_token])
            
            stdout = self._run_command(args)
            
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                raise GWSCommandError("Failed to parse gws output as JSON.")

            connections = data.get("connections", [])
            for person in connections:
                resource_name = person.get("resourceName", "")
                contact = self._parse_person(person)
                self._cache[resource_name] = contact
                contacts.append(contact)
            
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        
        return contacts

    def get_contact(self, resource_name: str) -> Optional[StandardContact]:
        """Retrieve a single contact, using cache if available."""
        if resource_name in self._cache:
            return self._cache[resource_name]
        
        # If not in cache, fetch specifically
        stdout = self._run_command([
            "people", "get", resource_name,
            "--read-mask", "names,emailAddresses,urls,imClients,phoneNumbers,metadata"
        ])
        
        try:
            person = json.loads(stdout)
            contact = self._parse_person(person)
            self._cache[resource_name] = contact
            return contact
        except (json.JSONDecodeError, GWSCommandError):
            return None

    def _parse_person(self, person: dict[str, Any]) -> StandardContact:
        """Parse a gws person object into a StandardContact."""
        resource_name = person.get("resourceName", "")
        etag = person.get("etag", "")
        
        # Extract display name
        names = person.get("names", [])
        display_name = names[0].get("displayName", "Unnamed") if names else "Unnamed"
        
        # Extract emails
        emails = [e.get("value") for e in person.get("emailAddresses", []) if e.get("value")]
        
        # Extract URLs/Handles
        urls = [u.get("value") for u in person.get("urls", []) if u.get("value")]
        
        # Extract IMs
        im_clients = [im.get("username") for im in person.get("imClients", []) if im.get("username")]
        
        # Extract phones
        phones = [p.get("value") for p in person.get("phoneNumbers", []) if p.get("value")]
        
        contact = StandardContact(
            source_id=resource_name, # For Google contacts, resourceName acts as the stable ID
            display_name=display_name,
            emails=emails,
            phones=phones,
            urls=urls,
            imClients=im_clients,
            raw_metadata={"etag": etag}
        )
        return contact
