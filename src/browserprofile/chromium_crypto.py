"""Chromium encrypted-value decryptors (v10 / v11).

Ported from yt-dlp (public domain): ``ChromeCookieDecryptor`` and the
``Linux/Mac/Windows`` subclasses plus ``get_cookie_decryptor`` from
``yt_dlp/cookies.py``.

The same ``v10``/``v11`` scheme protects cookie values, saved passwords
(``Login Data``) and credit-card numbers (``Web Data``), so a single decryptor
serves all three. ``meta_version`` controls the 32-byte SHA-256 hash prefix that
Chromium >= v24 prepends to *cookie* plaintext only; pass ``meta_version=0`` for
passwords/cards so no prefix is stripped.
"""
from __future__ import annotations

import functools
import sys

from ._aes import decrypt_aes_cbc_multi, decrypt_aes_gcm, pbkdf2_sha1
from .keyrings import (
    get_linux_keyring_password,
    get_mac_keyring_password,
    get_windows_v10_key,
    _decrypt_windows_dpapi,
)


class ChromeCookieDecryptor:
    _cookie_counts: dict = {}

    def decrypt(self, encrypted_value):
        raise NotImplementedError("Must be implemented by sub classes")


def get_chromium_decryptor(browser_root, browser_keyring_name, logger, *, keyring=None, meta_version=0):
    if sys.platform == "darwin":
        return MacChromeCookieDecryptor(browser_keyring_name, logger, meta_version=meta_version)
    elif sys.platform in ("win32", "cygwin"):
        return WindowsChromeCookieDecryptor(browser_root, logger, meta_version=meta_version)
    return LinuxChromeCookieDecryptor(browser_keyring_name, logger, keyring=keyring, meta_version=meta_version)


class LinuxChromeCookieDecryptor(ChromeCookieDecryptor):
    def __init__(self, browser_keyring_name, logger, *, keyring=None, meta_version=0):
        self._logger = logger
        self._v10_key = self.derive_key(b"peanuts")
        self._empty_key = self.derive_key(b"")
        self._cookie_counts = {"v10": 0, "v11": 0, "other": 0}
        self._browser_keyring_name = browser_keyring_name
        self._keyring = keyring
        self._meta_version = meta_version or 0

    @functools.cached_property
    def _v11_key(self):
        password = get_linux_keyring_password(self._browser_keyring_name, self._keyring, self._logger)
        return None if password is None else self.derive_key(password)

    @staticmethod
    def derive_key(password):
        return pbkdf2_sha1(password, salt=b"saltysalt", iterations=1, key_length=16)

    def decrypt(self, encrypted_value):
        version = encrypted_value[:3]
        ciphertext = encrypted_value[3:]

        if version == b"v10":
            self._cookie_counts["v10"] += 1
            return decrypt_aes_cbc_multi(
                ciphertext, (self._v10_key, self._empty_key), self._logger,
                hash_prefix=self._meta_version >= 24)
        elif version == b"v11":
            self._cookie_counts["v11"] += 1
            if self._v11_key is None:
                self._logger.warning("cannot decrypt v11 values: no key found", only_once=True)
                return None
            return decrypt_aes_cbc_multi(
                ciphertext, (self._v11_key, self._empty_key), self._logger,
                hash_prefix=self._meta_version >= 24)
        else:
            self._logger.warning(f'unknown value version: "{version}"', only_once=True)
            self._cookie_counts["other"] += 1
            return None


class MacChromeCookieDecryptor(ChromeCookieDecryptor):
    def __init__(self, browser_keyring_name, logger, meta_version=0):
        self._logger = logger
        password = get_mac_keyring_password(browser_keyring_name, logger)
        self._v10_key = None if password is None else self.derive_key(password)
        self._cookie_counts = {"v10": 0, "other": 0}
        self._meta_version = meta_version or 0

    @staticmethod
    def derive_key(password):
        return pbkdf2_sha1(password, salt=b"saltysalt", iterations=1003, key_length=16)

    def decrypt(self, encrypted_value):
        version = encrypted_value[:3]
        ciphertext = encrypted_value[3:]

        if version == b"v10":
            self._cookie_counts["v10"] += 1
            if self._v10_key is None:
                self._logger.warning("cannot decrypt v10 values: no key found", only_once=True)
                return None
            return decrypt_aes_cbc_multi(
                ciphertext, (self._v10_key,), self._logger, hash_prefix=self._meta_version >= 24)
        else:
            self._cookie_counts["other"] += 1
            # non-v10 is 'old data' stored as plaintext
            return encrypted_value


class WindowsChromeCookieDecryptor(ChromeCookieDecryptor):
    def __init__(self, browser_root, logger, meta_version=0):
        self._logger = logger
        self._v10_key = get_windows_v10_key(browser_root, logger)
        self._cookie_counts = {"v10": 0, "other": 0}
        self._meta_version = meta_version or 0

    def decrypt(self, encrypted_value):
        version = encrypted_value[:3]
        ciphertext = encrypted_value[3:]

        if version == b"v10":
            self._cookie_counts["v10"] += 1
            if self._v10_key is None:
                self._logger.warning("cannot decrypt v10 values: no key found", only_once=True)
                return None

            nonce_length = 96 // 8
            authentication_tag_length = 16
            nonce = ciphertext[:nonce_length]
            raw = ciphertext[nonce_length:-authentication_tag_length]
            authentication_tag = ciphertext[-authentication_tag_length:]
            return decrypt_aes_gcm(
                raw, self._v10_key, nonce, authentication_tag, self._logger,
                hash_prefix=self._meta_version >= 24)
        else:
            self._cookie_counts["other"] += 1
            # any other prefix means the data is DPAPI encrypted
            return _decrypt_windows_dpapi(encrypted_value, self._logger).decode()
