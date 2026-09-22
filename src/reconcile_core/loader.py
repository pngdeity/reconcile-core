import json
from .google_adapter import GoogleAdapter, GWSCommandError
from .models import StandardContact


class EtagsConflictError(GWSCommandError):
    """Raised when a contact update fails due to an etag conflict (412)."""


class ContactLoader:
    def __init__(self, adapter: GoogleAdapter):
        self.adapter = adapter

    def apply_additions(self, resource_name: str, current: StandardContact, additions: StandardContact) -> None:
        """Apply new data to an existing contact using PATCH logic."""
        etag = current.raw_metadata.get("etag")
        if not etag:
            raise GWSCommandError(f"Cannot update {resource_name}: missing etag.")

        # NOTE: We merge current + additions to construct the full field lists
        # for the update body. This has a stale-write limitation: if another
        # client added data between our fetch and this update, those additions
        # may be clobbered when we send the merged list. The etag check below
        # partially guards against this for whole-contact modifications, but
        # does not protect against field-level race conditions.
        body = {
            "etag": etag,
            "emailAddresses": [{"value": e} for e in (current.emails + additions.emails)],
            "urls": [{"value": u} for u in (current.urls + additions.urls)],
            "imClients": [{"username": im} for im in (current.imClients + additions.imClients)],
            "phoneNumbers": [{"value": p} for p in (current.phones + additions.phones)],
        }

        update_fields: list[str] = []
        if additions.emails:
            update_fields.append("emailAddresses")
        if additions.urls:
            update_fields.append("urls")
        if additions.imClients:
            update_fields.append("imClients")
        if additions.phones:
            update_fields.append("phoneNumbers")

        if not update_fields:
            return

        try:
            self.adapter._run_command([
                "people", "update-contact", resource_name,
                "--update-person-fields", ",".join(update_fields),
                "--body", json.dumps(body)
            ])
        except GWSCommandError as e:
            error_text = f"{e} {e.stderr or ''}".lower()
            if any(indicator in error_text for indicator in ("412", "failed_precondition", "etag")):
                raise EtagsConflictError(
                    f"Contact {resource_name} was modified since last read. Please re-fetch and try again.",
                    e.stderr,
                )
            raise
