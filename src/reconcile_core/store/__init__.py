"""Canonical contacts store: schema, migrations, helpers, and label vocabulary.

The store is the single source of truth for entities and their contact points;
Google Contacts and other generated files are projections of it.
"""

from .backup import default_backup_path, restore, snapshot, verify
from .bridge import (
    IM_SERVICE,
    contact_from_entity,
    find_entity_by_email,
    write_contact,
)
from .labels import CANONICAL, SOCIAL_SERVICES, normalize_label, service_from_label
from .migrate import apply_migrations, discover, status
from .store import (
    DEFAULT_DB,
    ENTITY_FIELDS,
    ENTITY_TYPES,
    KINDS,
    add_address,
    add_alias,
    add_contact_point,
    add_decision_state,
    add_external_ref,
    add_segment_member,
    connect,
    counts,
    create_entity,
    default_db_path,
    ensure_segment,
    get_entity_by_ref,
    mint_uid,
)

__all__ = [
    "IM_SERVICE",
    "contact_from_entity",
    "find_entity_by_email",
    "write_contact",
    "default_backup_path",
    "restore",
    "snapshot",
    "verify",
    "CANONICAL",
    "SOCIAL_SERVICES",
    "normalize_label",
    "service_from_label",
    "apply_migrations",
    "discover",
    "status",
    "DEFAULT_DB",
    "ENTITY_FIELDS",
    "ENTITY_TYPES",
    "KINDS",
    "add_address",
    "add_alias",
    "add_contact_point",
    "add_decision_state",
    "add_external_ref",
    "add_segment_member",
    "connect",
    "counts",
    "create_entity",
    "default_db_path",
    "ensure_segment",
    "get_entity_by_ref",
    "mint_uid",
]
