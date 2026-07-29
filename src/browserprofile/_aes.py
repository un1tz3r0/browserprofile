"""Low-level AES / KDF primitives used by the Chromium cookie decryptors.

Ported from yt-dlp (public domain / Unlicense): the functions
``_decrypt_aes_cbc_multi`` / ``_decrypt_aes_gcm`` / ``pbkdf2_sha1`` and the
``unpad_pkcs7`` helper from ``yt_dlp/cookies.py`` and ``yt_dlp/aes.py``.

yt-dlp keeps a pure-Python AES fallback for interpreters without pycryptodome;
we hard-require ``pycryptodomex`` instead, so these are thin wrappers.
"""
from __future__ import annotations

import hashlib

from Cryptodome.Cipher import AES


def aes_cbc_decrypt_bytes(data: bytes, key: bytes, iv: bytes) -> bytes:
    return AES.new(key, AES.MODE_CBC, iv).decrypt(data)


def aes_gcm_decrypt_and_verify_bytes(data: bytes, key: bytes, tag: bytes, nonce: bytes) -> bytes:
    return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(data, tag)


def unpad_pkcs7(data: bytes) -> bytes:
    return data[: -data[-1]]


def pbkdf2_sha1(password: bytes, salt: bytes, iterations: int, key_length: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", password, salt, iterations, key_length)


def decrypt_aes_cbc_multi(ciphertext, keys, logger, initialization_vector=b" " * 16, hash_prefix=False):
    """Try each key in turn, returning the first that UTF-8-decodes. Mirrors
    yt-dlp's ``_decrypt_aes_cbc_multi`` (v10/v11 Linux + macOS cookies)."""
    for key in keys:
        plaintext = unpad_pkcs7(aes_cbc_decrypt_bytes(ciphertext, key, initialization_vector))
        try:
            if hash_prefix:
                return plaintext[32:].decode()
            return plaintext.decode()
        except UnicodeDecodeError:
            pass
    logger.warning(
        "failed to decrypt value (AES-CBC) because UTF-8 decoding failed. Possibly the key is wrong?",
        only_once=True,
    )
    return None


def decrypt_aes_gcm(ciphertext, key, nonce, authentication_tag, logger, hash_prefix=False):
    """Windows v10 cookies: AES-GCM. Mirrors yt-dlp's ``_decrypt_aes_gcm``."""
    try:
        plaintext = aes_gcm_decrypt_and_verify_bytes(ciphertext, key, authentication_tag, nonce)
    except ValueError:
        logger.warning(
            "failed to decrypt value (AES-GCM) because the MAC check failed. Possibly the key is wrong?",
            only_once=True,
        )
        return None

    try:
        if hash_prefix:
            return plaintext[32:].decode()
        return plaintext.decode()
    except UnicodeDecodeError:
        logger.warning(
            "failed to decrypt value (AES-GCM) because UTF-8 decoding failed. Possibly the key is wrong?",
            only_once=True,
        )
        return None
