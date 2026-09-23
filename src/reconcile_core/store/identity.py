"""Identity resolution over the canonical store.

Deterministic, explainable duplicate *suggestions* plus lossless entity merge
and split. Name similarity replaces the legacy ``fuzzy_match_name`` helper: it
is used to surface candidates for a human to confirm, never to auto-merge. The
zero-loss principle applies — merging moves data, it never drops it.

Functions here do not commit; the caller owns the transaction.
"""

from __future__ import annotations

import difflib
import re
import sqlite3
from dataclasses import dataclass

from . import store as _store

_NAME_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_NAME_TOKEN = 3
_MAX_NAME_BUCKET = 50

_SHARE_KINDS = {
    "email": "email",
    "phone": "phone",
    "url": "url",
    "handle": "handle",
}


def normalize_name(value: str) -> str:
    """Case- and punctuation-insensitive form of a display name."""
    return " ".join(_NAME_TOKEN_RE.findall((value or "").lower()))


def name_similarity(a: str, b: str) -> float:
    """Ratio in ``[0, 1]`` between two display names (1.0 = identical tokens)."""
    left = normalize_name(a)
    right = normalize_name(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _norm_email(value: str) -> str:
    return value.strip().lower()


def _norm_phone(value: str) -> str:
    return re.sub(r"[^0-9]", "", value.lstrip("+"))


def _norm_url(value: str) -> str:
    return value.strip().rstrip("/").lower()


def _point_key(kind: str, value: str, service: str | None) -> tuple[str, str]:
    if kind == "email":
        return kind, _norm_email(value)
    if kind == "phone":
        return kind, _norm_phone(value)
    if kind == "url":
        return kind, _norm_url(value)
    if kind == "handle":
        return kind, f"{(service or '').strip().lower()}:{value.strip().lower()}"
    return kind, value.strip().lower()


@dataclass(frozen=True)
class DuplicateCandidate:
    """A scored suggestion that two entities may be the same person."""

    entity_a: int
    entity_b: int
    score: float
    shared: tuple[str, ...]
    name_similarity: float

    def as_dict(self) -> dict:
        return {
            "entity_a": self.entity_a,
            "entity_b": self.entity_b,
            "score": self.score,
            "shared": list(self.shared),
            "name_similarity": self.name_similarity,
        }


def _score(shared: set[str], sim: float) -> float:
    score = 0.0
    if "email" in shared:
        score += 0.55
    if "phone" in shared:
        score += 0.50
    if "handle" in shared:
        score += 0.30
    if "url" in shared:
        score += 0.20
    if sim >= 1.0:
        score += 0.45
    elif sim >= 0.9:
        score += 0.30
    elif sim >= 0.75:
        score += 0.15
    return min(score, 1.0)


def _shared_kind_pairs(conn: sqlite3.Connection) -> dict[tuple[int, int], set[str]]:
    index: dict[tuple[str, str], set[int]] = {}
    for row in conn.execute(
        "SELECT entity_id, kind, value, service FROM contact_points"
    ):
        key = _point_key(row["kind"], row["value"], row["service"])
        index.setdefault(key, set()).add(row["entity_id"])

    pairs: dict[tuple[int, int], set[str]] = {}
    for (kind, _), ids in index.items():
        label = _SHARE_KINDS.get(kind)
        if label is None or len(ids) < 2:
            continue
        ordered = sorted(ids)
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                pairs.setdefault((left, right), set()).add(label)
    return pairs


def _name_candidate_pairs(
    conn: sqlite3.Connection,
) -> tuple[set[tuple[int, int]], dict[int, str]]:
    names: dict[int, str] = {}
    tokens: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT id, display_name FROM entities"
        " WHERE display_name IS NOT NULL AND trim(display_name) != ''"
    ):
        entity_id, display_name = row["id"], row["display_name"]
        names[entity_id] = display_name
        for token in set(_NAME_TOKEN_RE.findall(display_name.lower())):
            if len(token) >= _MIN_NAME_TOKEN:
                tokens.setdefault(token, []).append(entity_id)

    pairs: set[tuple[int, int]] = set()
    for ids in tokens.values():
        ordered = sorted(set(ids))
        if len(ordered) < 2 or len(ordered) > _MAX_NAME_BUCKET:
            continue
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                pairs.add((left, right))
    return pairs, names


def find_duplicates(
    conn: sqlite3.Connection, *, min_score: float = 0.5
) -> list[DuplicateCandidate]:
    """Suggest likely duplicate entities, highest confidence first.

    Two entities are compared when they share a normalized contact point
    (email/phone/url/handle) or a meaningful display-name token. The score
    combines those signals; ``min_score`` filters low-confidence noise.
    """
    shared = _shared_kind_pairs(conn)
    name_pairs, names = _name_candidate_pairs(conn)

    for pair in name_pairs:
        shared.setdefault(pair, set())

    candidates: list[DuplicateCandidate] = []
    for (a, b), kinds in shared.items():
        sim = name_similarity(names.get(a, ""), names.get(b, ""))
        score = _score(kinds, sim)
        if score >= min_score:
            candidates.append(
                DuplicateCandidate(
                    entity_a=a,
                    entity_b=b,
                    score=round(score, 3),
                    shared=tuple(sorted(kinds)),
                    name_similarity=round(sim, 3),
                )
            )

    candidates.sort(key=lambda c: (-c.score, c.entity_a, c.entity_b))
    return candidates


def _dedupe_contact_points(conn: sqlite3.Connection, entity_id: int) -> int:
    """Drop exact normalized duplicates on an entity, keeping the first.

    A duplicate is only removed when it carries no address and no decision
    state, so nothing recoverable is lost.
    """
    seen: set[tuple[str, str]] = set()
    removed = 0
    rows = conn.execute(
        "SELECT id, kind, value, service FROM contact_points"
        " WHERE entity_id = ? ORDER BY is_primary DESC, id",
        (entity_id,),
    ).fetchall()
    for row in rows:
        key = _point_key(row["kind"], row["value"], row["service"])
        if key not in seen:
            seen.add(key)
            continue
        has_address = (
            conn.execute(
                "SELECT 1 FROM addresses WHERE contact_point_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            is not None
        )
        has_decision = (
            conn.execute(
                "SELECT 1 FROM decision_state WHERE contact_point_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            is not None
        )
        if has_address or has_decision:
            continue
        conn.execute("DELETE FROM contact_points WHERE id = ?", (row["id"],))
        removed += 1
    return removed


def _renumber_positions(
    conn: sqlite3.Connection, entity_id: int, preferred: list[int]
) -> int:
    """Give every contact-point kind a unique ``1..n`` position sequence.

    Points keep their relative order, but ids in ``preferred`` (the target's
    own points, captured before a fold) are placed first so a merge never
    displaces the surviving entity's existing slots. Without this a folded
    point can share a ``position`` with a target point, and the Google
    Contacts exporter — which keys slots by position — silently drops one.
    """
    rank = {point_id: index for index, point_id in enumerate(preferred)}
    changed = 0
    kinds = [
        row["kind"]
        for row in conn.execute(
            "SELECT DISTINCT kind FROM contact_points WHERE entity_id = ?",
            (entity_id,),
        )
    ]
    for kind in kinds:
        rows = conn.execute(
            "SELECT id, position FROM contact_points WHERE entity_id = ? AND kind = ?",
            (entity_id, kind),
        ).fetchall()
        ordered = sorted(
            rows,
            key=lambda row: (
                rank.get(row["id"], len(rank)),
                row["position"] if row["position"] is not None else 0,
                row["id"],
            ),
        )
        for position, row in enumerate(ordered, start=1):
            if row["position"] != position:
                conn.execute(
                    "UPDATE contact_points SET position = ? WHERE id = ?",
                    (position, row["id"]),
                )
                changed += 1
    return changed


def merge_entities(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    *,
    source: str = "merge",
    reason: str | None = None,
) -> dict:
    """Fold ``source_id`` into ``target_id`` without losing data.

    Moves every child row (refs, contact points and their addresses, aliases,
    segment membership, decision state, external status), preserves the
    source's display name as an alias when it differs, drops only exact
    normalized duplicates that carry no address/decision state, renumbers
    positions per kind so no two points share a slot, then deletes the source
    entity.
    """
    if source_id == target_id:
        raise ValueError("cannot merge an entity into itself")
    src = conn.execute("SELECT * FROM entities WHERE id = ?", (source_id,)).fetchone()
    dst = conn.execute("SELECT * FROM entities WHERE id = ?", (target_id,)).fetchone()
    if src is None:
        raise ValueError(f"no entity with id {source_id}")
    if dst is None:
        raise ValueError(f"no entity with id {target_id}")

    target_points = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM contact_points WHERE entity_id = ?", (target_id,)
        )
    ]

    stats = {
        "refs": conn.execute(
            "UPDATE external_refs SET entity_id = ? WHERE entity_id = ?",
            (target_id, source_id),
        ).rowcount,
        "contact_points": conn.execute(
            "UPDATE contact_points SET entity_id = ? WHERE entity_id = ?",
            (target_id, source_id),
        ).rowcount,
        "aliases": conn.execute(
            "UPDATE OR IGNORE aliases SET entity_id = ? WHERE entity_id = ?",
            (target_id, source_id),
        ).rowcount,
        "decision_state": conn.execute(
            "UPDATE decision_state SET entity_id = ? WHERE entity_id = ?",
            (target_id, source_id),
        ).rowcount,
        "external_status": conn.execute(
            "UPDATE external_status SET entity_id = ? WHERE entity_id = ?",
            (target_id, source_id),
        ).rowcount,
        "segment_members": conn.execute(
            "INSERT OR IGNORE INTO segment_members (segment_id, entity_id)"
            " SELECT segment_id, ? FROM segment_members WHERE entity_id = ?",
            (target_id, source_id),
        ).rowcount,
    }
    conn.execute("DELETE FROM segment_members WHERE entity_id = ?", (source_id,))
    conn.execute("DELETE FROM aliases WHERE entity_id = ?", (source_id,))

    source_name = (src["display_name"] or "").strip()
    target_name = (dst["display_name"] or "").strip()
    if source_name and source_name != target_name:
        _store.add_alias(conn, target_id, "name", source_name, source=source)
        if not target_name:
            conn.execute(
                "UPDATE entities SET display_name = ? WHERE id = ?",
                (source_name, target_id),
            )

    stats["duplicate_points"] = _dedupe_contact_points(conn, target_id)
    stats["points_renumbered"] = _renumber_positions(conn, target_id, target_points)
    conn.execute("DELETE FROM entities WHERE id = ?", (source_id,))
    conn.execute(
        "INSERT INTO audit_log (resource_name, action, delta) VALUES (?, ?, ?)",
        (
            f"entity:{target_id}",
            "MERGE",
            f"merged entity:{source_id}" + (f" ({reason})" if reason else ""),
        ),
    )
    return {"source_id": source_id, "target_id": target_id, **stats}


def split_entity(
    conn: sqlite3.Connection,
    entity_id: int,
    *,
    refs: list[tuple[str, str]] | None = None,
    contact_point_ids: list[int] | None = None,
    display_name: str | None = None,
    entity_type: str = "person",
    source: str = "split",
) -> int:
    """Move selected refs/contact points off ``entity_id`` onto a new entity.

    Returns the new entity id. Every requested ref or point must belong to the
    entity or a ``ValueError`` is raised (so a typo cannot silently no-op).
    """
    refs = list(refs or [])
    contact_point_ids = list(contact_point_ids or [])
    if not refs and not contact_point_ids:
        raise ValueError("nothing to split")

    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"no entity with id {entity_id}")

    new_id = _store.create_entity(
        conn,
        type=entity_type,
        display_name=display_name if display_name is not None else row["display_name"],
    )

    moved_refs = 0
    for source_name, ref_value in refs:
        cur = conn.execute(
            "UPDATE external_refs SET entity_id = ?"
            " WHERE entity_id = ? AND source = ? AND ref_value = ?",
            (new_id, entity_id, source_name, str(ref_value)),
        )
        if cur.rowcount == 0:
            raise ValueError(
                f"ref {source_name}:{ref_value} is not on entity {entity_id}"
            )
        moved_refs += 1

    moved_points = 0
    for point_id in contact_point_ids:
        cur = conn.execute(
            "UPDATE contact_points SET entity_id = ? WHERE id = ? AND entity_id = ?",
            (new_id, point_id, entity_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"contact point {point_id} is not on entity {entity_id}")
        moved_points += 1

    conn.execute(
        "INSERT INTO audit_log (resource_name, action, delta) VALUES (?, ?, ?)",
        (
            f"entity:{new_id}",
            "SPLIT",
            f"split from entity:{entity_id}"
            f" ({moved_refs} ref(s), {moved_points} point(s)) [{source}]",
        ),
    )
    return new_id
