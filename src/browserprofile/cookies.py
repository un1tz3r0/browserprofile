"""Cookie extraction (Chromium + Firefox).

The Chromium path (decryptor construction, meta_version, is_secure column
detection, v10/v11 handling) is ported from yt-dlp's ``_extract_chrome_cookies``
/ ``_process_chrome_cookie`` and the Firefox path from
``_extract_firefox_cookies`` (public domain). Adapted to return
:class:`~browserprofile.records.Cookie` dataclasses (with httponly / samesite,
needed for faithful CDP replay) instead of an ``http.cookiejar`` jar.
"""
from __future__ import annotations

from ._paths import get_column_names, newest, find_files, open_database_copy
from .chromium_crypto import get_chromium_decryptor
from .errors import ProfileNotFoundError
from .logger import Logger
from .profiles import Profile
from .records import Cookie, chrome_time, unix_seconds

# Chromium samesite column: -1 unspecified, 0 none, 1 lax, 2 strict
_CHROMIUM_SAMESITE = {-1: None, 0: "None", 1: "Lax", 2: "Strict"}
# Firefox sameSite column: 0 none, 1 lax, 2 strict
_FIREFOX_SAMESITE = {0: "None", 1: "Lax", 2: "Strict"}


def extract_cookies(profile: Profile, logger: Logger | None = None, keyring: str | None = None) -> list[Cookie]:
    logger = logger or Logger()
    if profile.family == "chromium":
        return _extract_chromium(profile, logger, keyring)
    return _extract_firefox(profile, logger)


def _extract_chromium(profile: Profile, logger: Logger, keyring: str | None) -> list[Cookie]:
    db_path = newest(find_files(str(profile.path), "Cookies"))
    if db_path is None:
        raise ProfileNotFoundError(f'no Cookies database under "{profile.path}"')

    out: list[Cookie] = []
    with open_database_copy(db_path) as cursor:
        meta_version = int(cursor.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0])
        decryptor = get_chromium_decryptor(
            str(profile.root), profile.keyring_name, logger, keyring=keyring, meta_version=meta_version)

        cursor.connection.text_factory = bytes
        columns = get_column_names(cursor, "cookies")
        secure_col = "is_secure" if "is_secure" in columns else "secure"
        httponly_col = "is_httponly" if "is_httponly" in columns else "httponly"
        cursor.execute(
            f"SELECT host_key, name, value, encrypted_value, path, expires_utc, "
            f"{secure_col}, {httponly_col}, samesite FROM cookies")
        for row in cursor.fetchall():
            host, name, value, enc, path, expires_utc, secure, httponly, samesite = row
            host, name, value, path = host.decode(), name.decode(), value.decode(), path.decode()
            if not value and enc:
                value = decryptor.decrypt(enc)
                if value is None:
                    continue
            # samesite comes back as bytes because of text_factory
            samesite_int = int(samesite) if samesite not in (None, b"") else -1
            out.append(Cookie(
                host=host, name=name, value=value, path=path,
                secure=bool(secure), http_only=bool(httponly),
                same_site=_CHROMIUM_SAMESITE.get(samesite_int),
                expires=chrome_time(int(expires_utc)) if expires_utc else None,
                browser=profile.browser, profile=profile.name))
    return out


def _extract_firefox(profile: Profile, logger: Logger) -> list[Cookie]:
    db_path = newest(find_files(str(profile.path), "cookies.sqlite"))
    if db_path is None:
        raise ProfileNotFoundError(f'no cookies.sqlite under "{profile.path}"')

    out: list[Cookie] = []
    with open_database_copy(db_path) as cursor:
        schema = cursor.execute("PRAGMA user_version;").fetchone()[0]
        cursor.execute(
            "SELECT host, name, value, path, expiry, isSecure, isHttpOnly, sameSite FROM moz_cookies")
        for host, name, value, path, expiry, secure, httponly, samesite in cursor.fetchall():
            # FF142 (schema >= 16) switched cookie expiry to milliseconds
            expires = None
            if expiry:
                expires = unix_seconds(expiry / 1000 if schema >= 16 else expiry)
            out.append(Cookie(
                host=host, name=name, value=value, path=path,
                secure=bool(secure), http_only=bool(httponly),
                same_site=_FIREFOX_SAMESITE.get(samesite),
                expires=expires, browser=profile.browser, profile=profile.name))
    return out
