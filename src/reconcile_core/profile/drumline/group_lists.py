"""Build the Google Groups target and run lists from the store.

Target addresses = every email on an entity in the ``illini-drumline-alumni``
segment, deduped by Gmail-normalized key, plus any address recorded as
``additional_address_confirmed``. In-group status comes from the latest
``external_status`` snapshot; routing comes from ``decision_state``
(``invite_required``, ``blocked``, ``held``).

Outputs (PII — pass explicit directories, nothing is written under the repo):
    <target-dir>/group_target.csv
    <target-dir>/group_remaining.csv
    <run-dir>/google_remaining.txt   (direct-add)
    <run-dir>/other_remaining.txt    (invite, .edu scheduled last)
    <run-dir>/skip_members.txt

Read-only with respect to the store.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from collections import defaultdict
from pathlib import Path

from ...store import connect

CHANNEL = "google_groups"
ALUMNI_SEGMENT = "illini-drumline-alumni"
CONSUMER_GOOGLE = {"gmail.com", "googlemail.com", "google.com"}
FIELDS = ("Email", "In_Group", "Is_Edu", "Person", "Person_ID", "Sources")

_mx_cache: dict[str, list[str]] = {}


def norm(email: str) -> str:
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        return local.replace(".", "") + "@gmail.com"
    return email


def mx_hosts(domain: str) -> list[str]:
    if domain not in _mx_cache:
        try:
            out = subprocess.run(
                ["dig", "+short", "MX", domain],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            hosts = [
                line.split()[-1].rstrip(".").lower()
                for line in out.splitlines()
                if line.strip()
            ]
        except Exception:
            hosts = []
        _mx_cache[domain] = hosts
    return _mx_cache[domain]


def is_google(domain: str) -> bool:
    if domain in CONSUMER_GOOGLE:
        return True
    return any(
        h.endswith("google.com") or h.endswith("googlemail.com")
        for h in mx_hosts(domain)
    )


def latest_status(conn) -> dict[str, tuple[str, str]]:
    """{address_lower: (status, email_status)} for the newest snapshot."""
    row = conn.execute(
        "SELECT MAX(observed_at) AS d FROM external_status WHERE channel = ?",
        (CHANNEL,),
    ).fetchone()
    if not row or not row["d"]:
        return {}
    out = {}
    for r in conn.execute(
        "SELECT address, status, email_status FROM external_status"
        " WHERE channel = ? AND observed_at = ?",
        (CHANNEL, row["d"]),
    ):
        out[r["address"].strip().lower()] = (r["status"], r["email_status"])
    return out


def routing(conn, status: str) -> dict[str, bool]:
    """{address_lower: True} for the decision_state statuses of interest."""
    out: dict[str, bool] = {}
    for r in conn.execute(
        """
        SELECT cp.value AS value
        FROM decision_state d
        LEFT JOIN contact_points cp ON cp.id = d.contact_point_id
        WHERE d.status = ?
        """,
        (status,),
    ):
        if r["value"]:
            out[r["value"].strip().lower()] = True
    return out


def build(conn, held_keys: set[str]):
    seg = conn.execute(
        "SELECT id FROM segments WHERE name = ?", (ALUMNI_SEGMENT,)
    ).fetchone()
    if not seg:
        raise SystemExit(f"segment not found: {ALUMNI_SEGMENT}")

    statuses = latest_status(conn)
    in_group = {norm(a) for a in statuses}

    entries = defaultdict(
        lambda: {"variants": set(), "person": "", "pid": "", "sources": set()}
    )
    meta = {}
    for r in conn.execute(
        """
        SELECT m.entity_id AS eid, e.display_name, e.first_name, e.last_name
        FROM segment_members m JOIN entities e ON e.id = m.entity_id
        WHERE m.segment_id = ?
        """,
        (seg["id"],),
    ):
        name = (
            r["display_name"]
            or " ".join(x for x in (r["first_name"], r["last_name"]) if x)
        ).strip()
        meta[r["eid"]] = {"name": name, "tracker": None, "sources": set()}
    for r in conn.execute(
        "SELECT entity_id, source, ref_value FROM external_refs"
        " WHERE source IN ('tracker_id','google_contacts_id')"
    ):
        if r["entity_id"] in meta:
            meta[r["entity_id"]]["sources"].add(r["source"])
            if r["source"] == "tracker_id" and meta[r["entity_id"]]["tracker"] is None:
                meta[r["entity_id"]]["tracker"] = str(r["ref_value"])

    for eid, m in meta.items():
        for cp in conn.execute(
            "SELECT value FROM contact_points WHERE entity_id = ? AND kind = 'email'"
            " ORDER BY position",
            (eid,),
        ):
            value = (cp["value"] or "").strip()
            if not value:
                continue
            d = entries[norm(value)]
            d["variants"].add(value)
            d["person"] = d["person"] or m["name"]
            d["pid"] = d["pid"] or (m["tracker"] or f"E{eid}")
            for s in m["sources"]:
                d["sources"].add("tracker" if s == "tracker_id" else "contacts")

    for addr in routing(conn, "additional_address_confirmed"):
        d = entries.setdefault(
            norm(addr), {"variants": set(), "person": "", "pid": "", "sources": set()}
        )
        d["variants"].add(addr)
        d["sources"].add("manual")

    rows, held = [], []
    for key, d in entries.items():
        variants = sorted(d["variants"])
        is_in = any(norm(v) in in_group for v in variants)
        canonical = next((v for v in variants if norm(v) in in_group), variants[0])
        record = {
            "Email": canonical,
            "In_Group": "yes" if is_in else "no",
            "Is_Edu": "yes" if canonical.lower().endswith(".edu") else "no",
            "Person": d["person"],
            "Person_ID": d["pid"],
            "Sources": ",".join(sorted(d["sources"])),
        }
        if key in held_keys:
            held.append(record)
        else:
            rows.append(record)

    rows.sort(
        key=lambda r: (r["In_Group"] == "yes", r["Is_Edu"] == "yes", r["Email"].lower())
    )
    held.sort(key=lambda r: r["Email"].lower())
    return rows, held


def write_target(target_dir: Path, rows, held) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)

    def w(path: Path, records) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records)

    remaining = [r for r in rows if r["In_Group"] == "no"]
    w(target_dir / "group_target.csv", rows)
    w(target_dir / "group_remaining.csv", remaining)
    nonedu = sum(1 for r in remaining if r["Is_Edu"] == "no")
    edu = sum(1 for r in remaining if r["Is_Edu"] == "yes")
    print(
        f"Target addresses: {len(rows)}  "
        f"(in group: {sum(1 for r in rows if r['In_Group'] == 'yes')})"
    )
    print(
        f"Remaining to add: {len(remaining)}  -> {nonedu} non-.edu, "
        f"{edu} .edu (scheduled last)"
    )
    print(f"Held (pending decision): {len(held)}")
    print(
        f"Wrote {target_dir / 'group_target.csv'} and {target_dir / 'group_remaining.csv'}"
    )


def write_run_lists(run_dir: Path, conn, remaining) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    force_invite = routing(conn, "invite_required")
    blocked = routing(conn, "blocked")
    statuses = latest_status(conn)
    google, other, routed, deferred = [], [], [], []
    for r in remaining:
        email = (r.get("Email") or "").strip()
        if not email:
            continue
        domain = email.rsplit("@", 1)[-1].lower()
        if email.lower() in blocked:
            deferred.append(email)
        elif email.lower() in force_invite:
            other.append(email)
            routed.append(email)
        elif is_google(domain):
            google.append(email)
        else:
            other.append(email)

    (run_dir / "google_remaining.txt").write_text("\n".join(google) + "\n")
    (run_dir / "other_remaining.txt").write_text("\n".join(other) + "\n")

    skip = set(statuses) | set(routing(conn, "held"))
    (run_dir / "skip_members.txt").write_text("\n".join(sorted(skip)) + "\n")

    workspace = sorted({e.rsplit("@", 1)[-1].lower() for e in google} - CONSUMER_GOOGLE)
    edu_other = [e for e in other if e.lower().endswith(".edu")]
    print(f"Remaining total: {len(google) + len(other)}")
    print(f"  google_remaining.txt (direct-add): {len(google)}")
    print(
        f"  other_remaining.txt  (invite):     {len(other)}  "
        f"({len(edu_other)} .edu, scheduled last)"
    )
    print(f"  skip_members.txt     (never submit): {len(skip)}")
    print(f"  non-consumer Google domains found: {workspace or 'none'}")
    print(
        f"  invite-required routed out of direct-add: {len(routed)}"
        + (f" ({', '.join(routed)})" if routed else "")
    )
    print(
        f"  blocked (deferred, not submitted): {len(deferred)}"
        + (f" ({', '.join(deferred)})" if deferred else "")
    )


def build_group_lists(db_path=None, target_dir=None, run_dir=None) -> dict:
    if target_dir is None or run_dir is None:
        raise SystemExit("--target-dir and --run-dir are required")
    conn = connect(db_path)
    try:
        held_keys = set(routing(conn, "held"))
        rows, held = build(conn, held_keys)
        write_target(Path(target_dir), rows, held)
        remaining = [r for r in rows if r["In_Group"] == "no"]
        write_run_lists(Path(run_dir), conn, remaining)
        return {"target": len(rows), "remaining": len(remaining), "held": len(held)}
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Google Groups target and run lists from the store"
    )
    parser.add_argument("--target-dir", required=True, help="output dir for the CSVs")
    parser.add_argument("--run-dir", required=True, help="output dir for the run lists")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    build_group_lists(args.db, args.target_dir, args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
