"""Saved-password and credit-card extraction (Chromium + Firefox).

  * Chromium passwords: ``Login Data`` db, ``logins`` table. ``password_value``
    is protected by the same v10/v11 scheme as cookies, so we reuse
    :func:`chromium_crypto.get_chromium_decryptor` (with ``meta_version=0`` — the
    cookie hash prefix does not apply to passwords).
  * Chromium cards: ``Web Data`` db, ``credit_cards`` table
    (``card_number_encrypted``), same decryptor.
  * Firefox passwords: delegated to :mod:`firefox_crypto` (NSS key4.db).
"""
from __future__ import annotations

from ._paths import find_files, newest, open_database_copy
from .chromium_crypto import get_chromium_decryptor
from .errors import ProfileNotFoundError
from .logger import Logger
from .profiles import Profile
from .records import CreditCard, Login, chrome_time, unix_seconds


def extract_logins(profile: Profile, logger: Logger | None = None, keyring: str | None = None) -> list[Login]:
    logger = logger or Logger()
    if profile.family == "chromium":
        return _extract_chromium_logins(profile, logger, keyring)
    return _extract_firefox_logins(profile)


def extract_credit_cards(profile: Profile, logger: Logger | None = None, keyring: str | None = None) -> list[CreditCard]:
    logger = logger or Logger()
    if profile.family == "chromium":
        return _extract_chromium_cards(profile, logger, keyring)
    return []  # Firefox does not store credit cards in the profile


def _extract_chromium_logins(profile: Profile, logger: Logger, keyring: str | None) -> list[Login]:
    db_path = newest(find_files(str(profile.path), "Login Data"))
    if db_path is None:
        raise ProfileNotFoundError(f'no "Login Data" database under "{profile.path}"')

    decryptor = get_chromium_decryptor(str(profile.root), profile.keyring_name, logger, keyring=keyring, meta_version=0)
    out: list[Login] = []
    with open_database_copy(db_path) as cursor:
        cursor.execute(
            "SELECT origin_url, username_value, password_value, date_created FROM logins")
        for origin_url, username, password_blob, date_created in cursor.fetchall():
            password = ""
            if password_blob:
                decrypted = decryptor.decrypt(bytes(password_blob))
                if decrypted is None:
                    continue
                password = decrypted
            out.append(Login(
                url=origin_url or "", username=username or "", password=password,
                date_created=chrome_time(date_created),
                browser=profile.browser, profile=profile.name))
    return out


def _extract_chromium_cards(profile: Profile, logger: Logger, keyring: str | None) -> list[CreditCard]:
    db_path = newest(find_files(str(profile.path), "Web Data"))
    if db_path is None:
        raise ProfileNotFoundError(f'no "Web Data" database under "{profile.path}"')

    decryptor = get_chromium_decryptor(str(profile.root), profile.keyring_name, logger, keyring=keyring, meta_version=0)
    out: list[CreditCard] = []
    with open_database_copy(db_path) as cursor:
        cursor.execute(
            "SELECT name_on_card, expiration_month, expiration_year, card_number_encrypted "
            "FROM credit_cards")
        for name, exp_month, exp_year, number_blob in cursor.fetchall():
            number = ""
            if number_blob:
                decrypted = decryptor.decrypt(bytes(number_blob))
                if decrypted is None:
                    continue
                number = decrypted
            out.append(CreditCard(
                name_on_card=name or "", expiration_month=exp_month or None,
                expiration_year=exp_year or None, card_number=number,
                browser=profile.browser, profile=profile.name))
    return out


def _extract_firefox_logins(profile: Profile) -> list[Login]:
    from .firefox_crypto import decrypt_logins

    out: list[Login] = []
    for row in decrypt_logins(profile.path):
        ms = row.get("time_created_ms")
        out.append(Login(
            url=row["hostname"], username=row["username"], password=row["password"],
            date_created=unix_seconds(ms / 1000) if ms else None,
            browser=profile.browser, profile=profile.name))
    return out
