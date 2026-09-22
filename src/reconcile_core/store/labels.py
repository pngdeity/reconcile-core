"""Canonical label vocabulary and helpers for the contacts store.

`label_norm` is a small controlled vocabulary per contact-point kind; the
original text is always preserved in `label_raw`. Anything not recognized maps
to `other` so every labeled point has a normalized value.
"""

EMAIL_LABELS = ("home", "work", "school", "other")
PHONE_LABELS = ("mobile", "home", "work", "other")
ADDRESS_LABELS = ("home", "work", "other")
URL_LABELS = ("home", "work", "other")

CANONICAL = {
    "email": EMAIL_LABELS,
    "phone": PHONE_LABELS,
    "address": ADDRESS_LABELS,
    "url": URL_LABELS,
}

_EMAIL_NORM = {
    "home": "home",
    "home (preferred)": "home",
    "work": "work",
    "school": "school",
}
_PHONE_NORM = {
    "mobile": "mobile",
    "cell": "mobile",
    "cell?": "mobile",
    "iphone": "mobile",
    "home": "home",
    "work": "work",
    "office": "work",
    "business": "work",
    "main": "work",
    "unknown work": "work",
    "whatsapp": "other",
    "former mobile": "other",
    "fax": "other",
    "unknown": "other",
    "other": "other",
}
_ADDRESS_NORM = {"home": "home", "work": "work"}
_URL_NORM = {"home": "home", "work": "work"}

_MAPS = {
    "email": _EMAIL_NORM,
    "phone": _PHONE_NORM,
    "address": _ADDRESS_NORM,
    "url": _URL_NORM,
}

SOCIAL_SERVICES = {
    "linkedin": "linkedin",
    "facebook": "facebook",
    "twitter": "twitter",
    "x": "x",
    "instagram": "instagram",
    "github": "github",
    "github commit": "github",
    "venmo": "venmo",
    "discord": "discord",
    "reddit": "reddit",
    "matrix": "matrix",
    "tiktok": "tiktok",
    "youtube": "youtube",
}


def base_key(raw: str | None) -> str:
    return (raw or "").strip().lstrip("*").strip().lower()


def normalize_label(raw: str | None, kind: str) -> str | None:
    if not raw or not raw.strip():
        return None
    return _MAPS.get(kind, {}).get(base_key(raw), "other")


def service_from_label(raw: str | None) -> str | None:
    return SOCIAL_SERVICES.get(base_key(raw))
