"""Firefox saved-login decryption (NSS key4.db + logins.json).

This is NOT ported from yt-dlp (which does not decrypt Firefox logins). It
implements the NSS password-manager scheme, following the well-documented
approach of firepwd/firefox_decrypt:

  * ``key4.db`` holds a global salt (metadata) and a PBE-wrapped 3DES master key
    (nssPrivate). The wrapping PBE is either legacy pkcs12 3DES
    (``1.2.840.113549.1.12.5.1.3``) or modern PBES2/AES-256-CBC
    (``1.2.840.113549.1.5.13``).
  * ``logins.json`` holds per-site usernames/passwords encrypted with 3DES-CBC
    under that master key.

Only the default (empty) master password is supported; a user-set master
password would need to be supplied to :func:`decrypt_logins`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

from Cryptodome.Cipher import AES, DES3
from pyasn1.codec.der import decoder as der_decoder

from ._aes import unpad_pkcs7
from ._paths import open_database_copy
from .errors import DecryptionError

_OID_3DES_PBE = "1.2.840.113549.1.12.5.1.3"
_OID_PBES2 = "1.2.840.113549.1.5.13"
_PASSWORD_CHECK = b"password-check\x02\x02"


def _sha1(data: bytes) -> bytes:
    return hashlib.sha1(data).digest()


def _decrypt_3des(global_salt: bytes, master_password: bytes, entry_salt: bytes, ciphertext: bytes) -> bytes:
    """NSS's pkcs12 SHA1+3DES key derivation and decrypt."""
    hp = _sha1(global_salt + master_password)
    pes = entry_salt + b"\x00" * (20 - len(entry_salt))
    chp = _sha1(hp + entry_salt)
    k1 = hmac.new(chp, pes + entry_salt, hashlib.sha1).digest()
    tk = hmac.new(chp, pes, hashlib.sha1).digest()
    k2 = hmac.new(chp, tk + entry_salt, hashlib.sha1).digest()
    k = k1 + k2
    iv = k[-8:]
    key = k[:24]
    return DES3.new(key, DES3.MODE_CBC, iv).decrypt(ciphertext)


def _decrypt_pbe(decoded_item, master_password: bytes, global_salt: bytes) -> bytes:
    """Decrypt a metadata/nssPrivate PBE item (either 3DES-PBE or PBES2/AES).

    Structure (verified against a real key4.db)::

        SEQUENCE {
          SEQUENCE {                 # [0] AlgorithmIdentifier
            OID pbeAlgo,             # [0][0]
            <params>                 # [0][1]
          },
          OCTET STRING cipherText    # [1]
        }
    """
    pbe_algo = str(decoded_item[0][0])
    cipher_text = decoded_item[1].asOctets()
    if pbe_algo == _OID_3DES_PBE:
        # params: SEQUENCE { OCTET STRING entrySalt, INTEGER iterationCount }
        entry_salt = decoded_item[0][1][0].asOctets()
        return _decrypt_3des(global_salt, master_password, entry_salt, cipher_text)
    elif pbe_algo == _OID_PBES2:
        # params: SEQUENCE { PBKDF2-params-seq, encryption-scheme-seq }
        pbkdf2_params = decoded_item[0][1][0][1]
        entry_salt = pbkdf2_params[0].asOctets()
        iteration_count = int(pbkdf2_params[1])
        key_length = int(pbkdf2_params[2])
        k = _sha1(global_salt + master_password)
        key = hashlib.pbkdf2_hmac("sha256", k, entry_salt, iteration_count, dklen=key_length)
        # NSS uses the DER TLV encoding of the 14-byte salt (tag 04, len 0e) as the 16-byte IV
        iv = b"\x04\x0e" + decoded_item[0][1][1][1].asOctets()
        return AES.new(key, AES.MODE_CBC, iv).decrypt(cipher_text)
    raise DecryptionError(f"unsupported Firefox PBE algorithm: {pbe_algo}")


def get_master_key(key4_path: str, master_password: bytes = b"") -> bytes:
    """Recover the 24-byte 3DES master key from key4.db."""
    with open_database_copy(key4_path) as cursor:
        row = cursor.execute(
            "SELECT item1, item2 FROM metadata WHERE id = 'password'").fetchone()
        if row is None:
            raise DecryptionError("no password entry in key4.db metadata")
        global_salt, item2 = row

        decoded_item2, _ = der_decoder.decode(item2)
        check = _decrypt_pbe(decoded_item2, master_password, global_salt)
        if check[: len(_PASSWORD_CHECK)] != _PASSWORD_CHECK:
            raise DecryptionError(
                "Firefox master-password check failed; a master password is likely set")

        row = cursor.execute(
            "SELECT a11 FROM nssPrivate WHERE a11 IS NOT NULL").fetchone()
        if row is None:
            raise DecryptionError("no key found in key4.db nssPrivate table")
        decoded_a11, _ = der_decoder.decode(row[0])
        key = _decrypt_pbe(decoded_a11, master_password, global_salt)
        return key[:24]


def _decode_login_blob(b64data: str) -> tuple[bytes, bytes]:
    decoded, _ = der_decoder.decode(base64.b64decode(b64data))
    iv = decoded[1][1].asOctets()
    ciphertext = decoded[2].asOctets()
    return iv, ciphertext


def decrypt_logins(profile_path: Path, master_password: bytes = b"") -> list[dict]:
    """Return decrypted logins for a Firefox profile.

    Each item: ``{hostname, username, password, time_created_ms}``. Returns an
    empty list if the profile has no saved logins.
    """
    key4 = profile_path / "key4.db"
    logins_json = profile_path / "logins.json"
    if not key4.is_file() or not logins_json.is_file():
        return []

    key = get_master_key(str(key4), master_password)
    data = json.loads(logins_json.read_text(encoding="utf8"))

    results = []
    for entry in data.get("logins", []):
        try:
            iv, ct = _decode_login_blob(entry["encryptedUsername"])
            username = unpad_pkcs7(DES3.new(key, DES3.MODE_CBC, iv).decrypt(ct)).decode("utf8", "replace")
            iv, ct = _decode_login_blob(entry["encryptedPassword"])
            password = unpad_pkcs7(DES3.new(key, DES3.MODE_CBC, iv).decrypt(ct)).decode("utf8", "replace")
        except (ValueError, KeyError) as e:
            raise DecryptionError(f"failed to decrypt a Firefox login: {e}") from e
        results.append({
            "hostname": entry.get("hostname", ""),
            "username": username,
            "password": password,
            "time_created_ms": entry.get("timeCreated"),
        })
    return results
