"""Point-in-time snapshots of profile data, and diffs between them.

A checkpoint is a plain dict (JSON-serializable) holding every extractor's
records for one or more profiles. :func:`diff_checkpoints` reports what was
added, removed or changed between two checkpoints of the same shape.

Secret values (cookie values, saved passwords, card numbers) are handled per the
``secrets`` mode:

* ``"hash"`` (default) stores a short deterministic digest, so a diff can tell
  that a value changed without the checkpoint ever holding the value. The digest
  is deterministic (equal values hash equal across checkpoints, which is what
  makes it diffable); it confirms equality, it is not a defence against brute
  force of a low-entropy value.
* ``"exclude"`` drops secret values entirely (the field is kept as ``None`` so
  the record shape is stable). A value-only change can't be detected.
* ``"decrypted"`` stores the real values. The checkpoint is then a plaintext
  secret store — only for when exact before/after values are needed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Iterable

from .autofill import extract_autofill
from .bookmarks import extract_bookmarks
from .cookies import extract_cookies
from .errors import BrowserProfileError
from .history import extract_history
from .logger import Logger
from .passwords import extract_credit_cards, extract_logins
from .profiles import Profile

VERSION = 1
SECRET_MODES = ("hash", "exclude", "decrypted")
_SALT = b"browserprofile-checkpoint-v1"

# kind -> extractor
_EXTRACTORS = {
    "cookies": extract_cookies,
    "history": extract_history,
    "bookmarks": extract_bookmarks,
    "autofill": extract_autofill,
    "logins": extract_logins,
    "cards": extract_credit_cards,
}

# kind -> fields that identify a record (never include a secret field here)
_IDENTITY = {
    "cookies": ("browser", "profile", "host", "name", "path"),
    "history": ("browser", "profile", "url"),
    "bookmarks": ("browser", "profile", "url", "folder"),
    "autofill": ("browser", "profile", "field_name", "value"),
    "logins": ("browser", "profile", "url", "username"),
    "cards": ("browser", "profile", "name_on_card", "expiration_month", "expiration_year"),
}

# kind -> fields whose values are secret
_SECRET_FIELDS = {
    "cookies": ("value",),
    "logins": ("password",),
    "cards": ("card_number",),
}


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(_SALT + value.encode()).hexdigest()[:16]


def _apply_secrets(kind: str, record: dict, secrets: str) -> dict:
    for field in _SECRET_FIELDS.get(kind, ()):
        value = record.get(field)
        if not value or secrets == "decrypted":
            continue
        record[field] = _hash(value) if secrets == "hash" else None
    return record


def build_checkpoint(
    profiles: Iterable[Profile],
    *,
    secrets: str = "hash",
    logger: Logger | None = None,
    keyring: str | None = None,
) -> dict:
    """Snapshot every extractor's records for ``profiles`` into a dict.

    A profile that a given extractor can't read (no such database) is skipped for
    that kind rather than failing the whole checkpoint.
    """
    if secrets not in SECRET_MODES:
        raise ValueError(f"secrets must be one of {SECRET_MODES}, not {secrets!r}")
    logger = logger or Logger()
    profiles = list(profiles)

    records: dict[str, list[dict]] = {}
    for kind, extractor in _EXTRACTORS.items():
        rows: list[dict] = []
        for profile in profiles:
            try:
                extracted = extractor(profile, logger, keyring=keyring)
            except BrowserProfileError:
                continue
            for record in extracted:
                rows.append(_apply_secrets(kind, record.to_dict(), secrets))
        records[kind] = rows

    return {
        "version": VERSION,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sources": sorted({p.label for p in profiles}),
        "secrets": secrets,
        "records": records,
    }


def _by_identity(kind: str, rows: list[dict]) -> dict[tuple, dict]:
    keys = _IDENTITY[kind]
    return {tuple(row.get(k) for k in keys): row for row in rows}


def diff_checkpoints(before: dict, after: dict) -> dict:
    """Compare two checkpoints, returning per-kind added / removed / changed.

    ``changed`` lists only the names of the fields that differ, never their
    values, so a diff stays safe to print whatever the ``secrets`` mode was.
    """
    out: dict[str, dict] = {}
    for kind, identity in _IDENTITY.items():
        before_rows = _by_identity(kind, before["records"].get(kind, []))
        after_rows = _by_identity(kind, after["records"].get(kind, []))

        added = [after_rows[k] for k in after_rows.keys() - before_rows.keys()]
        removed = [before_rows[k] for k in before_rows.keys() - after_rows.keys()]
        changed = []
        for key in before_rows.keys() & after_rows.keys():
            old, new = before_rows[key], after_rows[key]
            fields = sorted(
                field for field in old.keys() | new.keys()
                if field not in identity and old.get(field) != new.get(field))
            if fields:
                changed.append({"key": dict(zip(identity, key)), "changed_fields": fields})

        out[kind] = {"added": added, "removed": removed, "changed": changed}
    return out
