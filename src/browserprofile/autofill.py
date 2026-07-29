"""Form-autofill extraction (Chromium + Firefox).

Plaintext in both families:
  * Chromium: ``Web Data`` db, ``autofill`` table. Note its date columns are
    Unix-epoch *seconds* (time_t), unlike History's 1601-epoch microseconds.
  * Firefox: ``formhistory.sqlite``, ``moz_formhistory`` (lastUsed is a
    1970-epoch microsecond PRTime).
"""
from __future__ import annotations

from ._paths import find_files, newest, open_database_copy
from .errors import ProfileNotFoundError
from .logger import Logger
from .profiles import Profile
from .records import AutofillEntry, unix_micros, unix_seconds


def extract_autofill(profile: Profile, logger: Logger | None = None, keyring: str | None = None) -> list[AutofillEntry]:
    logger = logger or Logger()  # keyring is unused (autofill is plaintext); kept for a uniform interface
    if profile.family == "chromium":
        return _extract_chromium(profile)
    return _extract_firefox(profile)


def _extract_chromium(profile: Profile) -> list[AutofillEntry]:
    db_path = newest(find_files(str(profile.path), "Web Data"))
    if db_path is None:
        raise ProfileNotFoundError(f'no Web Data database under "{profile.path}"')

    out: list[AutofillEntry] = []
    with open_database_copy(db_path) as cursor:
        cursor.execute("SELECT name, value, count, date_last_used FROM autofill")
        for name, value, count, date_last_used in cursor.fetchall():
            out.append(AutofillEntry(
                field_name=name or "", value=value or "", use_count=count or 0,
                last_used=unix_seconds(date_last_used),
                browser=profile.browser, profile=profile.name))
    return out


def _extract_firefox(profile: Profile) -> list[AutofillEntry]:
    db_path = newest(find_files(str(profile.path), "formhistory.sqlite"))
    if db_path is None:
        raise ProfileNotFoundError(f'no formhistory.sqlite under "{profile.path}"')

    out: list[AutofillEntry] = []
    with open_database_copy(db_path) as cursor:
        cursor.execute("SELECT fieldname, value, timesUsed, lastUsed FROM moz_formhistory")
        for fieldname, value, times_used, last_used in cursor.fetchall():
            out.append(AutofillEntry(
                field_name=fieldname or "", value=value or "", use_count=times_used or 0,
                last_used=unix_micros(last_used),
                browser=profile.browser, profile=profile.name))
    return out
