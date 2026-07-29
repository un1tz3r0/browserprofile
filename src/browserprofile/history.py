"""Browsing-history extraction (Chromium + Firefox).

History is plaintext SQLite in both families, so no decryption is involved:
  * Chromium: ``History`` db, ``urls`` table (one row per URL with visit_count
    and last_visit_time as a 1601-epoch microsecond timestamp).
  * Firefox: ``places.sqlite``, ``moz_places`` table (last_visit_date as a
    1970-epoch microsecond PRTime).
"""
from __future__ import annotations

from ._paths import find_files, newest, open_database_copy
from .errors import ProfileNotFoundError
from .logger import Logger
from .profiles import Profile
from .records import HistoryEntry, chrome_time, unix_micros


def extract_history(profile: Profile, logger: Logger | None = None, keyring: str | None = None) -> list[HistoryEntry]:
    logger = logger or Logger()  # keyring is unused (history is plaintext); kept for a uniform interface
    if profile.family == "chromium":
        return _extract_chromium(profile)
    return _extract_firefox(profile)


def _extract_chromium(profile: Profile) -> list[HistoryEntry]:
    db_path = newest(find_files(str(profile.path), "History"))
    if db_path is None:
        raise ProfileNotFoundError(f'no History database under "{profile.path}"')

    out: list[HistoryEntry] = []
    with open_database_copy(db_path) as cursor:
        cursor.execute(
            "SELECT url, title, visit_count, last_visit_time FROM urls ORDER BY last_visit_time DESC")
        for url, title, visit_count, last_visit_time in cursor.fetchall():
            out.append(HistoryEntry(
                url=url, title=title or "", visit_count=visit_count or 0,
                last_visit=chrome_time(last_visit_time),
                browser=profile.browser, profile=profile.name))
    return out


def _extract_firefox(profile: Profile) -> list[HistoryEntry]:
    db_path = newest(find_files(str(profile.path), "places.sqlite"))
    if db_path is None:
        raise ProfileNotFoundError(f'no places.sqlite under "{profile.path}"')

    out: list[HistoryEntry] = []
    with open_database_copy(db_path) as cursor:
        cursor.execute(
            "SELECT url, title, visit_count, last_visit_date FROM moz_places "
            "WHERE last_visit_date IS NOT NULL ORDER BY last_visit_date DESC")
        for url, title, visit_count, last_visit_date in cursor.fetchall():
            out.append(HistoryEntry(
                url=url, title=title or "", visit_count=visit_count or 0,
                last_visit=unix_micros(last_visit_date),
                browser=profile.browser, profile=profile.name))
    return out
