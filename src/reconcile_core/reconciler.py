from typing import Any
from .models import StandardContact, ReconciliationDiff

import re

class Reconciler:
    def reconcile(self, proposed: StandardContact, current: StandardContact) -> ReconciliationDiff:
        """
        Compare a proposed contact from an adapter against the current Google contact.
        Implements the 'Zero-loss' principle with normalization:
        - Union: Append new unique data (URLs, Emails, Phones, etc.)
        - Conflict: Identify differences in primary fields (Display Name)
        """
        resource_name = current.source_id # source_id in current is the resourceName
        additions = StandardContact(
            source_id=proposed.source_id,
            display_name=""
        )
        collisions: dict[str, tuple[Any, Any]] = {}

        # 1. Name Conflict Check
        if proposed.display_name != current.display_name:
            collisions["display_name"] = (current.display_name, proposed.display_name)

        # 2. Email Union (Case-insensitive)
        normalized_current_emails = {e.lower() for e in current.emails}
        for email in proposed.emails:
            if email.lower() not in normalized_current_emails:
                additions.emails.append(email)

        # 3. URL/Handle Union (Case-insensitive & strip trailing slashes)
        normalized_current_urls = {u.rstrip('/').lower() for u in current.urls}
        for url in proposed.urls:
            if url.rstrip('/').lower() not in normalized_current_urls:
                additions.urls.append(url)

        # 4. IM Client Union (Case-insensitive)
        normalized_current_ims = {im.lower() for im in current.imClients}
        for im in proposed.imClients:
            if im.lower() not in normalized_current_ims:
                additions.imClients.append(im)

        # 5. Phone Union (strip non-digit chars & leading + for comparison)
        def _normalize_phone(p: str) -> str:
            return re.sub(r'[^0-9]', '', p.lstrip('+'))

        normalized_current_phones = {_normalize_phone(p) for p in current.phones}
        for phone in proposed.phones:
            if _normalize_phone(phone) not in normalized_current_phones:
                additions.phones.append(phone)

        return ReconciliationDiff(
            resource_name=resource_name,
            additions=additions,
            collisions=collisions
        )
