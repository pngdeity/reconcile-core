"""Apply core-store migrations plus the drumline profile's own migrations."""

from __future__ import annotations

from pathlib import Path

from ...store.migrate import apply_migrations, discover, status

PROFILE_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def apply_profile_migrations(db_path: Path | str | None = None) -> int:
    """Run core + drumline migrations; return the resulting schema version."""
    return apply_migrations(db_path, extra_dirs=[PROFILE_MIGRATIONS_DIR])


def profile_status(db_path: Path | str | None = None):
    """(version, name, applied) for core + drumline migrations."""
    return status(db_path, extra_dirs=[PROFILE_MIGRATIONS_DIR])


def all_migrations():
    """All discovered migrations (core + drumline), sorted by version."""
    return discover([PROFILE_MIGRATIONS_DIR])


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Apply core + drumline migrations to the contacts store"
    )
    parser.add_argument("--db", default=None, help="contacts store path")
    parser.add_argument("--status", action="store_true", help="show status only")
    args = parser.parse_args()

    if args.status:
        from ...store.store import default_db_path

        print(f"Database: {args.db or default_db_path()}")
        for version, name, applied in profile_status(args.db):
            print(f"  {version:04d}  {name:32s} {'applied' if applied else 'pending'}")
        return 0

    version = apply_profile_migrations(args.db)
    print(f"Now at version {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
