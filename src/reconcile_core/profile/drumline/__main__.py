"""Single CLI for the drumline profile.

Usage:
    uv run python -m reconcile_core.profile.drumline <command> [options]

Commands:
    migrate            apply core + drumline migrations
    import-drumline    link Tracker rows, alumni segment, decision state
    audition-members   apply audition name-fills + create new member entities
    name-resolutions   apply versioned manual name resolutions
    import-master      seed the outreach overlay from the legacy master CSV
    export-members     generate the person-level member CSV

Run ``<command> --help`` for options. See the package README for the PII
conventions (configs in ``var/drumline/``; data paths passed in).
"""

from __future__ import annotations

import sys

COMMANDS = (
    "migrate",
    "import-drumline",
    "audition-members",
    "name-resolutions",
    "import-master",
    "export-members",
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2

    command, rest = args[0], args[1:]
    if command not in COMMANDS:
        print(f"unknown command: {command!r}; expected one of {', '.join(COMMANDS)}")
        return 2

    from . import (
        audition_members,
        export_members,
        import_drumline,
        import_master,
        migrate,
        name_resolutions,
    )

    dispatch = {
        "migrate": migrate.main,
        "import-drumline": import_drumline.main,
        "audition-members": audition_members.main,
        "name-resolutions": name_resolutions.main,
        "import-master": import_master.main,
        "export-members": export_members.main,
    }
    sys.argv = [f"reconcile_core.profile.drumline {command}", *rest]
    return dispatch[command]()


if __name__ == "__main__":
    raise SystemExit(main())
