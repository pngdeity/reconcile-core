"""Canonical contacts store: schema, migrations, helpers, and label vocabulary.

The store is the single source of truth for entities and their contact points;
Google Contacts and other generated files are projections of it.
"""

from .bridge import (
    IM_SERVICE,
    contact_from_entity,
    find_entity_by_email,
    write_contact,
)
from .identity import (
    DuplicateCandidate,
    find_duplicates,
    merge_entities,
    name_similarity,
    normalize_name,
    split_entity,
)
from .labels import CANONICAL, SOCIAL_SERVICES, normalize_label, service_from_label
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
    "DuplicateCandidate",
    "find_duplicates",
    "merge_entities",
    "name_similarity",
    "normalize_name",
    "split_entity",
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

# Submodules that expose a ``__main__`` CLI are resolved lazily (PEP 562).
# Importing them during package init would make ``python -m
# reconcile_core.store.<mod>`` trigger runpy's "found in sys.modules" warning.
_LAZY_EXPORTS = {
    "apply_migrations": "migrate",
    "discover": "migrate",
    "status": "migrate",
    "default_backup_path": "backup",
    "restore": "backup",
    "snapshot": "backup",
    "verify": "backup",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value
