"""Unified command-line interface for reconcile-core.

Commands: ``migrate``, ``ingest``, ``resolve``, ``reconcile``, ``export``, ``audit``.
The store is the source of truth; adapters feed it and exports are projections.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .database import SQLitePersistence
from .io import export_contacts
from .reconciler import Reconciler
from .store import apply_migrations, connect, counts, find_entity_by_email
from .store import backup as store_backup
from .store import get_entity_by_ref
from .store.bridge import contact_from_entity, write_contact
from .store.migrate import status as migration_status

console = Console()


def _db(args) -> Path | None:
    return Path(args.db) if getattr(args, "db", None) else None


def _adapter(platform: str):
    from .main import ADAPTER_CLASSES

    cls = ADAPTER_CLASSES.get(platform)
    if cls is None:
        console.print(f"[red]Platform '{platform}' adapter not available.[/red]")
        sys.exit(1)
    return cls()


def cmd_migrate(args) -> int:
    db = _db(args)
    profile = getattr(args, "profile", None)
    if getattr(args, "status", False):
        if profile == "drumline":
            from .profile.drumline.migrate import profile_status

            rows = profile_status(db)
        else:
            rows = migration_status(db)
        for version, name, applied in rows:
            state = "applied" if applied else "pending"
            console.print(f"  {version:04d}  {name:32s} {state}")
        current = max((v for v, _, applied in rows if applied), default=0)
        console.print(f"[green]Store schema at version {current}[/green]")
        return 0
    version = apply_migrations(db)
    if profile == "drumline":
        from .profile.drumline.migrate import apply_profile_migrations

        version = apply_profile_migrations(db)
    console.print(f"[green]Store schema at version {version}[/green]")
    return 0


def cmd_backup(args) -> int:
    dest = Path(args.out) if getattr(args, "out", None) else None
    path = store_backup.snapshot(_db(args), dest)
    info = store_backup.verify(path)
    console.print(f"[green]Snapshot written to {path}[/green]")
    console.print(
        f"  schema version {info['schema_version']}, "
        f"{info['counts'].get('entities', 0)} entities"
    )
    return 0


def cmd_restore(args) -> int:
    path = store_backup.restore(args.snapshot, _db(args), force=args.force)
    console.print(f"[green]Store restored from {args.snapshot} to {path}[/green]")
    return 0


def cmd_ingest(args) -> int:
    adapter = _adapter(args.platform)
    persistence = SQLitePersistence(_db(args))
    total = created = 0
    added: Counter[str] = Counter()
    for contact in adapter.extract(Path(args.file)):
        stats = persistence.ingest(
            contact, platform=args.platform, source_id=contact.source_id
        )
        total += 1
        created += int(stats["created"])
        added.update(stats["added"])
    console.print(
        f"[green]Ingested {total} contact(s); {created} new entity(ies).[/green] "
        f"Added {dict(added)}"
    )
    return 0


def cmd_resolve(args) -> int:
    persistence = SQLitePersistence(_db(args))
    unresolved = persistence.list_unresolved()
    if not unresolved:
        console.print("[green]No unresolved identities.[/green]")
        return 0
    table = Table(title=f"Unresolved identities ({len(unresolved)})")
    table.add_column("platform")
    table.add_column("source_id")
    for platform, source_id in unresolved:
        table.add_row(str(platform), str(source_id))
    console.print(table)
    return 0


def cmd_reconcile(args) -> int:
    adapter = _adapter(args.platform)
    db = _db(args)
    apply_migrations(db)
    conn = connect(db)
    reconciler = Reconciler()
    rows = []
    applied = 0
    try:
        for proposed in adapter.extract(Path(args.file)):
            entity_id = get_entity_by_ref(conn, args.platform, str(proposed.source_id))
            if entity_id is None:
                for email in proposed.emails:
                    entity_id = find_entity_by_email(conn, email)
                    if entity_id is not None:
                        break

            if entity_id is None:
                rows.append((proposed.display_name, "unmatched", "0", "0"))
                continue

            current = contact_from_entity(conn, entity_id)
            diff = reconciler.reconcile(proposed, current)
            additions = sum(
                len(getattr(diff.additions, field))
                for field in ("emails", "phones", "urls", "handles", "imClients")
            )
            status = "no change"
            if additions or diff.collisions:
                status = "conflict" if diff.collisions else "additions"
                if args.apply and not args.dry_run:
                    write_contact(
                        conn, diff.additions, entity_id=entity_id, source="reconcile"
                    )
                    applied += 1
                    status = "applied"
            rows.append(
                (
                    proposed.display_name,
                    status,
                    str(additions),
                    str(len(diff.collisions)),
                )
            )
        conn.commit()
    finally:
        conn.close()

    table = Table(title=f"Reconcile: {args.file} (platform: {args.platform})")
    for column in ("Contact", "Result", "Additions", "Collisions"):
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    console.print(table)
    if args.apply and not args.dry_run:
        console.print(f"[green]Applied additions to {applied} entit(ies).[/green]")
    elif not args.dry_run:
        console.print(
            "[yellow]Dry run (default). Pass --apply to write additions.[/yellow]"
        )
    return 0


def cmd_export(args) -> int:
    db = _db(args)
    if args.what == "google-contacts":
        stats = export_contacts(out_dir=args.out or ".", db_path=db)
        console.print(
            f"[green]Wrote {stats.get('rows', '?')} row(s) to {stats.get('out_dir', args.out or '.')}[/green]"
        )
    else:
        from .profile.drumline.export_members import export_members

        export_members(args.out or "drumline-members.csv", db_path=db)
        console.print(f"[green]Wrote {args.out or 'drumline-members.csv'}[/green]")
    return 0


def cmd_audit(args) -> int:
    db = _db(args)
    apply_migrations(db)
    conn = connect(db)
    try:
        summary = counts(conn)
        contact_points = conn.execute(
            "SELECT kind, COUNT(*) AS n FROM contact_points GROUP BY kind ORDER BY kind"
        ).fetchall()
        entities = conn.execute(
            "SELECT type, COUNT(*) AS n FROM entities GROUP BY type ORDER BY type"
        ).fetchall()
    finally:
        conn.close()

    table = Table(title="Store audit")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for key, value in summary.items():
        table.add_row(key, str(value))
    console.print(table)

    kinds = ", ".join(f"{row['kind']}={row['n']}" for row in contact_points) or "none"
    types = ", ".join(f"{row['type']}={row['n']}" for row in entities) or "none"
    console.print(f"Contact points: {kinds}")
    console.print(f"Entities: {types}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconcile-core",
        description="Reconcile social identities into the canonical contacts store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def with_db(p):
        p.add_argument("--db", help="store DB path (default: repo var/contacts.db)")

    migrate = sub.add_parser("migrate", help="apply store (and profile) migrations")
    with_db(migrate)
    migrate.add_argument(
        "--profile", choices=["drumline"], help="also apply a profile's migrations"
    )
    migrate.add_argument(
        "--status", action="store_true", help="list applied migrations"
    )
    migrate.set_defaults(func=cmd_migrate)

    backup = sub.add_parser("backup", help="snapshot the store to a file")
    with_db(backup)
    backup.add_argument(
        "--out",
        help="destination file (default: <store-dir>/backups/<name>-<timestamp>.db)",
    )
    backup.set_defaults(func=cmd_backup)

    restore = sub.add_parser("restore", help="restore the store from a snapshot")
    with_db(restore)
    restore.add_argument("snapshot", help="snapshot file to restore")
    restore.add_argument(
        "--force", action="store_true", help="overwrite an existing store"
    )
    restore.set_defaults(func=cmd_restore)

    ingest = sub.add_parser("ingest", help="load an adapter export into the store")
    with_db(ingest)
    ingest.add_argument("file")
    ingest.add_argument("-p", "--platform", required=True)
    ingest.set_defaults(func=cmd_ingest)

    resolve = sub.add_parser("resolve", help="list unresolved identities")
    with_db(resolve)
    resolve.set_defaults(func=cmd_resolve)

    reconcile = sub.add_parser(
        "reconcile", help="diff an adapter export against store records"
    )
    with_db(reconcile)
    reconcile.add_argument("file")
    reconcile.add_argument("-p", "--platform", required=True)
    reconcile.add_argument(
        "--dry-run", action="store_true", help="preview only (default)"
    )
    reconcile.add_argument(
        "--apply", action="store_true", help="write additions (zero-loss union)"
    )
    reconcile.set_defaults(func=cmd_reconcile)

    export = sub.add_parser("export", help="write a projection of the store")
    with_db(export)
    export.add_argument("what", choices=["google-contacts", "drumline-members"])
    export.add_argument("--out", help="output directory or file")
    export.set_defaults(func=cmd_export)

    audit = sub.add_parser("audit", help="summarise store contents")
    with_db(audit)
    audit.set_defaults(func=cmd_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
