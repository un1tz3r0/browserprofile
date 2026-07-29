"""Structured records returned by the extractors, plus timestamp helpers.

Records carry raw structured fields (not export blobs) so downstream consumers —
e.g. the planned pydoll session-injection mixin — can replay them faithfully.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

_CHROME_EPOCH = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)
_UNIX_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def chrome_time(microseconds: int | None) -> dt.datetime | None:
    """Chromium/WebKit timestamp: microseconds since 1601-01-01 UTC."""
    if not microseconds:
        return None
    try:
        return _CHROME_EPOCH + dt.timedelta(microseconds=microseconds)
    except (OverflowError, OSError):
        return None


def unix_micros(microseconds: int | None) -> dt.datetime | None:
    """Firefox PRTime: microseconds since 1970-01-01 UTC."""
    if not microseconds:
        return None
    try:
        return _UNIX_EPOCH + dt.timedelta(microseconds=microseconds)
    except (OverflowError, OSError):
        return None


def unix_seconds(seconds: float | None) -> dt.datetime | None:
    if not seconds:
        return None
    try:
        return _UNIX_EPOCH + dt.timedelta(seconds=seconds)
    except (OverflowError, OSError):
        return None


def _convert(value):
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


@dataclass
class _Record:
    def to_dict(self) -> dict:
        return {k: _convert(v) for k, v in dataclasses.asdict(self).items()}


@dataclass
class Cookie(_Record):
    host: str
    name: str
    value: str
    path: str
    secure: bool
    http_only: bool
    same_site: str | None
    expires: dt.datetime | None
    browser: str
    profile: str


@dataclass
class HistoryEntry(_Record):
    url: str
    title: str
    visit_count: int
    last_visit: dt.datetime | None
    browser: str
    profile: str


@dataclass
class Bookmark(_Record):
    title: str
    url: str
    folder: str
    date_added: dt.datetime | None
    browser: str
    profile: str


@dataclass
class AutofillEntry(_Record):
    field_name: str
    value: str
    use_count: int
    last_used: dt.datetime | None
    browser: str
    profile: str


@dataclass
class Login(_Record):
    url: str
    username: str
    password: str
    date_created: dt.datetime | None
    browser: str
    profile: str


@dataclass
class CreditCard(_Record):
    name_on_card: str
    expiration_month: int | None
    expiration_year: int | None
    card_number: str
    browser: str
    profile: str
