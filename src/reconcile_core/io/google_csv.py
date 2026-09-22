"""Google Contacts CSV import/export.

The canonical store is the source of truth; Google Contacts CSV is a
projection. This module:

- **imports** Google's 62-column template (with the project ``ID`` column at
  position 0) into the store, and
- **exports** ``Contacts.csv`` (62 cols) and ``Contacts_import.csv`` (61 cols,
  ``ID`` stripped) from the store.

Only entities carrying a ``google_contacts_id`` external ref are exported.
One Contacts custom field is special: the alumni marker maps to a segment so
that drumline membership survives the round trip.
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import date
from pathlib import Path

from ..store import labels
from ..store import store as store_mod
from ..store.migrate import apply_migrations

SOURCE = "google-contacts-clean"

# The one Contacts custom field that is modelled as segment membership.
MARKER_LABEL = "Alumni Status"
MARKER_VALUE = "Illini Drumline"
MARKER_SEGMENT = "illini-drumline-alumni"

HEADER = [
    "ID",
    "First Name",
    "Middle Name",
    "Last Name",
    "Phonetic First Name",
    "Phonetic Middle Name",
    "Phonetic Last Name",
    "Name Prefix",
    "Name Suffix",
    "Nickname",
    "File As",
    "Organization Name",
    "Organization Title",
    "Organization Department",
    "Birthday",
    "Notes",
    "Photo",
    "Labels",
    "E-mail 1 - Label",
    "E-mail 1 - Value",
    "E-mail 2 - Label",
    "E-mail 2 - Value",
    "E-mail 3 - Label",
    "E-mail 3 - Value",
    "Phone 1 - Label",
    "Phone 1 - Value",
    "Phone 2 - Label",
    "Phone 2 - Value",
    "Phone 3 - Label",
    "Phone 3 - Value",
    "Address 1 - Label",
    "Address 1 - Formatted",
    "Address 1 - Street",
    "Address 1 - City",
    "Address 1 - PO Box",
    "Address 1 - Region",
    "Address 1 - Postal Code",
    "Address 1 - Country",
    "Address 1 - Extended Address",
    "Address 2 - Label",
    "Address 2 - Formatted",
    "Address 2 - Street",
    "Address 2 - City",
    "Address 2 - PO Box",
    "Address 2 - Region",
    "Address 2 - Postal Code",
    "Address 2 - Country",
    "Address 2 - Extended Address",
    "Relation 1 - Label",
    "Relation 1 - Value",
    "Relation 2 - Label",
    "Relation 2 - Value",
    "Website 1 - Label",
    "Website 1 - Value",
    "Website 2 - Label",
    "Website 2 - Value",
    "Custom Field 1 - Label",
    "Custom Field 1 - Value",
    "Custom Field 2 - Label",
    "Custom Field 2 - Value",
    "Custom Field 3 - Label",
    "Custom Field 3 - Value",
]

IMPORT_HEADER = [c for c in HEADER if c != "ID"]

ADDRESS_FIELDS = {
    "Formatted": "formatted",
    "Street": "street",
    "City": "city",
    "PO Box": "pobox",
    "Region": "region",
    "Postal Code": "postal",
    "Country": "country",
    "Extended Address": "extended",
}

ROLE_RE = re.compile(
    r"^(team|info|support|noreply|no-reply|donotreply|admin|contact|sales|hello|"
    r"help|office|webmaster|mail|accounts?|billing|orders|announcements|"
    r"donations|reply)@",
    re.IGNORECASE,
)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _norm_label(raw: str | None, kind: str) -> str | None:
    return labels.normalize_label(raw, kind)


def infer_type(row: dict) -> str:
    if _clean(row.get("First Name")) or _clean(row.get("Last Name")):
        return "person"
    if _clean(row.get("Organization Name")):
        return "org"
    emails = [_clean(row.get(f"E-mail {i} - Value")) for i in (1, 2, 3)]
    if any(e and ROLE_RE.match(e) for e in emails):
        return "service"
    return "person"


def import_contacts(
    path: str | Path,
    db_path: str | Path | None = None,
    *,
    source: str = SOURCE,
    import_date: str | None = None,
) -> dict:
    """Import a Google Contacts CSV into the store. Idempotent per row ID."""
    import_date = import_date or date.today().isoformat()
    db = Path(db_path) if db_path else store_mod.DEFAULT_DB
    db.parent.mkdir(parents=True, exist_ok=True)
    apply_migrations(db)

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    conn = store_mod.connect(db)
    try:
        seg = store_mod.ensure_segment(
            conn,
            MARKER_SEGMENT,
            description=f"Members carrying the {MARKER_LABEL} marker",
            definition=f"entity whose Custom Field 1 - Value == {MARKER_VALUE!r}",
        )
        created = skipped = alumni = 0
        points: dict[str, int] = {}

        def bump(kind: str) -> None:
            points[kind] = points.get(kind, 0) + 1

        for idx, row in enumerate(rows, 1):
            cid = _clean(row.get("ID"))
            if cid and store_mod.get_entity_by_ref(conn, "google_contacts_id", cid):
                skipped += 1
                continue

            name_parts = [_clean(row.get("First Name")), _clean(row.get("Last Name"))]
            display = " ".join(p for p in name_parts if p) or _clean(
                row.get("Organization Name")
            )
            entity_id = store_mod.create_entity(
                conn,
                type=infer_type(row),
                display_name=display,
                first_name=_clean(row.get("First Name")),
                middle_name=_clean(row.get("Middle Name")),
                last_name=_clean(row.get("Last Name")),
                nickname=_clean(row.get("Nickname")),
                org_name=_clean(row.get("Organization Name")),
                title=_clean(row.get("Organization Title")),
                department=_clean(row.get("Organization Department")),
                birthday=_clean(row.get("Birthday")),
                notes=_clean(row.get("Notes")),
            )
            if cid:
                store_mod.add_external_ref(conn, entity_id, "google_contacts_id", cid)

            first_email = True
            for i in (1, 2, 3):
                value = _clean(row.get(f"E-mail {i} - Value"))
                label = _clean(row.get(f"E-mail {i} - Label"))
                if value:
                    store_mod.add_contact_point(
                        conn,
                        entity_id,
                        "email",
                        value,
                        label_raw=label,
                        label_norm=_norm_label(label, "email"),
                        is_primary=first_email,
                        position=i,
                        source=source,
                    )
                    first_email = False
                    bump("email")
                elif label:
                    store_mod.add_alias(
                        conn,
                        entity_id,
                        "slot_label:email",
                        label,
                        source=source,
                        position=i,
                    )
                    bump("alias")

            first_phone = True
            for i in (1, 2, 3):
                value = _clean(row.get(f"Phone {i} - Value"))
                label = _clean(row.get(f"Phone {i} - Label"))
                if value:
                    store_mod.add_contact_point(
                        conn,
                        entity_id,
                        "phone",
                        value,
                        label_raw=label,
                        label_norm=_norm_label(label, "phone"),
                        is_primary=first_phone,
                        position=i,
                        source=source,
                    )
                    first_phone = False
                    bump("phone")
                elif label:
                    store_mod.add_alias(
                        conn,
                        entity_id,
                        "slot_label:phone",
                        label,
                        source=source,
                        position=i,
                    )
                    bump("alias")

            for i in (1, 2):
                formatted = _clean(row.get(f"Address {i} - Formatted"))
                parts = {
                    k: _clean(row.get(f"Address {i} - {k}"))
                    for k in (
                        "Street",
                        "City",
                        "Region",
                        "Postal Code",
                        "Country",
                        "PO Box",
                        "Extended Address",
                    )
                }
                if not formatted and not any(parts.values()):
                    label = _clean(row.get(f"Address {i} - Label"))
                    if label:
                        store_mod.add_alias(
                            conn,
                            entity_id,
                            "slot_label:address",
                            label,
                            source=source,
                            position=i,
                        )
                        bump("alias")
                    continue
                value = formatted or ", ".join(
                    p
                    for p in (
                        parts["Street"],
                        parts["City"],
                        parts["Region"],
                        parts["Postal Code"],
                        parts["Country"],
                    )
                    if p
                )
                cp_id = store_mod.add_contact_point(
                    conn,
                    entity_id,
                    "address",
                    value,
                    label_raw=_clean(row.get(f"Address {i} - Label")),
                    label_norm=_norm_label(row.get(f"Address {i} - Label"), "address"),
                    position=i,
                    source=source,
                )
                store_mod.add_address(
                    conn,
                    cp_id,
                    street=parts["Street"],
                    city=parts["City"],
                    region=parts["Region"],
                    postal=parts["Postal Code"],
                    country=parts["Country"],
                    pobox=parts["PO Box"],
                    extended=parts["Extended Address"],
                    formatted=formatted,
                )
                bump("address")

            for i in (1, 2):
                value = _clean(row.get(f"Website {i} - Value"))
                label = _clean(row.get(f"Website {i} - Label"))
                if value:
                    store_mod.add_contact_point(
                        conn,
                        entity_id,
                        "url",
                        value,
                        label_raw=label,
                        label_norm=_norm_label(label, "url"),
                        position=i,
                        source=source,
                    )
                    bump("url")
                elif label:
                    store_mod.add_alias(
                        conn,
                        entity_id,
                        "slot_label:url",
                        label,
                        source=source,
                        position=i,
                    )
                    bump("alias")

            photo = _clean(row.get("Photo"))
            if photo:
                store_mod.add_contact_point(
                    conn, entity_id, "url", photo, service="photo", source=source
                )
                bump("photo")

            for n in (1, 2, 3):
                label = _clean(row.get(f"Custom Field {n} - Label"))
                value = _clean(row.get(f"Custom Field {n} - Value"))
                if not label and not value:
                    continue
                key = (label or "").lower()
                if key == MARKER_LABEL.lower():
                    continue
                if key == "name pronunciation" and value:
                    store_mod.add_alias(
                        conn,
                        entity_id,
                        "pronunciation",
                        value,
                        source=source,
                        position=n,
                    )
                    bump("alias")
                elif value:
                    store_mod.add_contact_point(
                        conn,
                        entity_id,
                        "handle",
                        value,
                        label_raw=label,
                        service=labels.service_from_label(label) or key or None,
                        position=n,
                        source=source,
                    )
                    bump("handle")
                elif label:
                    store_mod.add_alias(
                        conn,
                        entity_id,
                        "custom_field_label",
                        label,
                        source=source,
                        position=n,
                    )
                    bump("alias")

            for n in (1, 2):
                label = _clean(row.get(f"Relation {n} - Label"))
                value = _clean(row.get(f"Relation {n} - Value"))
                if value:
                    store_mod.add_alias(
                        conn,
                        entity_id,
                        f"relation:{label}" if label else "relation",
                        value,
                        source=source,
                        position=n,
                    )
                    bump("alias")

            for col, kind in (
                ("Phonetic First Name", "phonetic:first"),
                ("Phonetic Middle Name", "phonetic:middle"),
                ("Phonetic Last Name", "phonetic:last"),
            ):
                value = _clean(row.get(col))
                if value:
                    store_mod.add_alias(conn, entity_id, kind, value, source=source)
                    bump("alias")

            if _clean(row.get("Custom Field 1 - Value")) == MARKER_VALUE:
                store_mod.add_segment_member(conn, seg, entity_id)
                alumni += 1

            created += 1
            if idx % 250 == 0:
                conn.commit()

        conn.commit()
        return {
            "rows": len(rows),
            "created": created,
            "skipped": skipped,
            "alumni": alumni,
            "points": points,
            "counts": store_mod.counts(conn),
            "import_date": import_date,
        }
    finally:
        conn.close()


def load_children(conn):
    points: dict[int, list] = {}
    addresses: dict[int, object] = {}
    aliases: dict[int, list] = {}
    for r in conn.execute(
        "SELECT * FROM contact_points ORDER BY entity_id, (position IS NULL), position, id"
    ):
        points.setdefault(r["entity_id"], []).append(r)
    for r in conn.execute("SELECT * FROM addresses"):
        addresses[r["contact_point_id"]] = r
    for r in conn.execute(
        "SELECT * FROM aliases ORDER BY entity_id, (position IS NULL), position, id"
    ):
        aliases.setdefault(r["entity_id"], []).append(r)
    markers = {
        r["entity_id"]
        for r in conn.execute(
            "SELECT sm.entity_id FROM segment_members sm "
            "JOIN segments s ON s.id = sm.segment_id WHERE s.name = ?",
            (MARKER_SEGMENT,),
        )
    }
    return points, addresses, aliases, markers


def build_rows(conn) -> list[dict]:
    entities = conn.execute(
        """
        SELECT e.*, x.ref_value AS gcid
        FROM entities e
        JOIN external_refs x
          ON x.entity_id = e.id AND x.source = 'google_contacts_id'
        ORDER BY CAST(x.ref_value AS INTEGER), e.id
        """
    ).fetchall()
    points, addresses, aliases, markers = load_children(conn)
    out = []

    for e in entities:
        row = {c: "" for c in HEADER}
        row["ID"] = e["gcid"]
        row["First Name"] = e["first_name"] or ""
        row["Middle Name"] = e["middle_name"] or ""
        row["Last Name"] = e["last_name"] or ""
        row["Nickname"] = e["nickname"] or ""
        row["Organization Name"] = e["org_name"] or ""
        row["Organization Title"] = e["title"] or ""
        row["Organization Department"] = e["department"] or ""
        row["Birthday"] = e["birthday"] or ""
        row["Notes"] = e["notes"] or ""

        pts = points.get(e["id"], [])
        als = aliases.get(e["id"], [])

        def slot_labels(kind):
            return {
                (a["position"] or 0): (a["alias_value"] or "")
                for a in als
                if a["alias_type"] == f"slot_label:{kind}"
            }

        emails = {(p["position"] or 0): p for p in pts if p["kind"] == "email"}
        elabels = slot_labels("email")
        for i in (1, 2, 3):
            p = emails.get(i)
            row[f"E-mail {i} - Label"] = (p["label_raw"] if p else "") or elabels.get(
                i, ""
            )
            row[f"E-mail {i} - Value"] = (p["value"] if p else "") or ""

        phones = {(p["position"] or 0): p for p in pts if p["kind"] == "phone"}
        plabels = slot_labels("phone")
        for i in (1, 2, 3):
            p = phones.get(i)
            row[f"Phone {i} - Label"] = (p["label_raw"] if p else "") or plabels.get(
                i, ""
            )
            row[f"Phone {i} - Value"] = (p["value"] if p else "") or ""

        addr_pts = {(p["position"] or 0): p for p in pts if p["kind"] == "address"}
        alabels = slot_labels("address")
        for i in (1, 2):
            p = addr_pts.get(i)
            a = addresses.get(p["id"]) if p else None
            row[f"Address {i} - Label"] = (p["label_raw"] if p else "") or alabels.get(
                i, ""
            )
            for col, attr in ADDRESS_FIELDS.items():
                row[f"Address {i} - {col}"] = (a[attr] if a and a[attr] else "") or ""

        url_pts = {
            (p["position"] or 0): p
            for p in pts
            if p["kind"] == "url" and (p["service"] or "") != "photo"
        }
        wlabels = slot_labels("url")
        for i in (1, 2):
            p = url_pts.get(i)
            row[f"Website {i} - Label"] = (p["label_raw"] if p else "") or wlabels.get(
                i, ""
            )
            row[f"Website {i} - Value"] = (p["value"] if p else "") or ""

        photo = [
            p for p in pts if p["kind"] == "url" and (p["service"] or "") == "photo"
        ]
        if photo:
            row["Photo"] = photo[0]["value"] or ""

        for a in als:
            if a["alias_type"] == "phonetic:first":
                row["Phonetic First Name"] = a["alias_value"] or ""
            elif a["alias_type"] == "phonetic:middle":
                row["Phonetic Middle Name"] = a["alias_value"] or ""
            elif a["alias_type"] == "phonetic:last":
                row["Phonetic Last Name"] = a["alias_value"] or ""

        rels = [
            a
            for a in als
            if a["alias_type"] == "relation" or a["alias_type"].startswith("relation:")
        ]
        for i, a in enumerate(rels[:2], 1):
            if ":" in a["alias_type"]:
                row[f"Relation {i} - Label"] = a["alias_type"].split(":", 1)[1]
            row[f"Relation {i} - Value"] = a["alias_value"] or ""

        cf_slot: dict[int, tuple[str, str]] = {}
        for p in pts:
            if p["kind"] == "handle":
                cf_slot[p["position"] or 1] = (p["value"] or "", p["label_raw"] or "")
        for a in als:
            if a["alias_type"] == "pronunciation":
                cf_slot[a["position"] or 1] = (
                    a["alias_value"] or "",
                    "Name pronunciation",
                )
        for a in als:
            if a["alias_type"] == "custom_field_label":
                cf_slot.setdefault(a["position"] or 1, ("", a["alias_value"] or ""))
        if e["id"] in markers:
            cf_slot[1] = (MARKER_VALUE, MARKER_LABEL)
        for n in (1, 2, 3):
            value, label = cf_slot.get(n, ("", ""))
            row[f"Custom Field {n} - Label"] = label
            row[f"Custom Field {n} - Value"] = value

        out.append(row)

    return out


def write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=header, quoting=csv.QUOTE_MINIMAL, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def export_contacts(
    out_dir: str | Path = ".", db_path: str | Path | None = None
) -> dict:
    """Write Contacts.csv (62 cols) and Contacts_import.csv (61 cols)."""
    db = Path(db_path) if db_path else store_mod.DEFAULT_DB
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    conn = store_mod.connect(db)
    try:
        rows = build_rows(conn)
    finally:
        conn.close()
    write_csv(out / "Contacts.csv", rows, HEADER)
    write_csv(out / "Contacts_import.csv", rows, IMPORT_HEADER)
    return {"rows": len(rows), "out_dir": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Google Contacts CSV import/export")
    parser.add_argument("--db", default=None, help="store path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="import a Contacts.csv into the store")
    p_import.add_argument("--input", required=True, help="Contacts.csv path")

    p_export = sub.add_parser("export", help="write Contacts.csv + Contacts_import.csv")
    p_export.add_argument("--out", default=".", help="output directory")

    args = parser.parse_args(argv)
    if args.command == "import":
        stats = import_contacts(args.input, args.db)
        print(
            f"Imported {stats['created']} entities "
            f"({stats['skipped']} skipped, {stats['alumni']} alumni)."
        )
    else:
        stats = export_contacts(args.out, args.db)
        print(f"Exported {stats['rows']} rows to {stats['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
