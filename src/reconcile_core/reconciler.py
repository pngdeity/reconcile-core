"""Zero-loss reconciliation of a proposed contact against a current one.

Emails, URLs, handles, IM clients, and phones are unioned with normalization;
display-name differences are surfaced as collisions and never auto-applied.
"""

import re
from typing import Any

from .models import ReconciliationDiff, SocialHandle, StandardContact


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_url(value: str) -> str:
    return value.strip().rstrip("/").lower()


def normalize_phone(value: str) -> str:
    return re.sub(r"[^0-9]", "", value.lstrip("+"))


def normalize_handle(handle: SocialHandle) -> tuple[str, str]:
    return (handle.platform.strip().lower(), handle.username.strip().lower())


class Reconciler:
    def reconcile(
        self, proposed: StandardContact, current: StandardContact
    ) -> ReconciliationDiff:
        """Compare a proposed contact against the current one.

        Implements the 'Zero-loss' principle with normalization:
        - Union: append new unique data (emails, URLs, handles, IM clients, phones)
        - Conflict: identify differences in primary fields (display name)
        """
        resource_name = current.source_id  # source_id in current is the resourceName
        additions = StandardContact(source_id=proposed.source_id, display_name="")
        collisions: dict[str, tuple[Any, Any]] = {}

        # 1. Name conflict check
        if proposed.display_name != current.display_name:
            collisions["display_name"] = (current.display_name, proposed.display_name)

        # 2. Email union (case-insensitive)
        current_emails = {normalize_email(e) for e in current.emails}
        for email in proposed.emails:
            if normalize_email(email) not in current_emails:
                additions.emails.append(email)

        # 3. URL union (case-insensitive, trailing slashes ignored)
        current_urls = {normalize_url(u) for u in current.urls}
        for url in proposed.urls:
            if normalize_url(url) not in current_urls:
                additions.urls.append(url)

        # 4. Social handle union (platform + username, case-insensitive)
        current_handles = {normalize_handle(h) for h in current.handles}
        for handle in proposed.handles:
            if normalize_handle(handle) not in current_handles:
                additions.handles.append(handle)

        # 5. IM client union (case-insensitive)
        current_ims = {im.lower() for im in current.imClients}
        for im in proposed.imClients:
            if im.lower() not in current_ims:
                additions.imClients.append(im)

        # 6. Phone union (compare digits only)
        current_phones = {normalize_phone(p) for p in current.phones}
        for phone in proposed.phones:
            if normalize_phone(phone) not in current_phones:
                additions.phones.append(phone)

        return ReconciliationDiff(
            resource_name=resource_name,
            additions=additions,
            collisions=collisions,
        )
