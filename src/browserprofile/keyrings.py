"""OS secret-store access for Chromium's ``v11`` cookie/login key.

Ported from yt-dlp (public domain): the ``_Linux*`` enums and detection,
``_get_kwallet_*``, ``_get_gnome_keyring_password``, ``_get_linux_keyring_password``,
``_get_mac_keyring_password``, ``_get_windows_v10_key`` and
``_decrypt_windows_dpapi`` from ``yt_dlp/cookies.py``.

Adaptations: ``Popen.run`` -> ``subprocess.run``; ``error_to_str`` -> ``str``;
yt-dlp's ``DownloadError`` -> :class:`DecryptionError`.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
import subprocess
import sys
from enum import Enum, auto

from ._paths import find_files, newest
from .errors import DecryptionError

try:
    import secretstorage
except ImportError:
    secretstorage = None


class _LinuxDesktopEnvironment(Enum):
    OTHER = auto()
    CINNAMON = auto()
    DEEPIN = auto()
    GNOME = auto()
    KDE3 = auto()
    KDE4 = auto()
    KDE5 = auto()
    KDE6 = auto()
    PANTHEON = auto()
    UKUI = auto()
    UNITY = auto()
    XFCE = auto()
    LXQT = auto()


class _LinuxKeyring(Enum):
    KWALLET = auto()  # KDE4
    KWALLET5 = auto()
    KWALLET6 = auto()
    GNOMEKEYRING = auto()
    BASICTEXT = auto()


SUPPORTED_KEYRINGS = _LinuxKeyring.__members__.keys()


def _get_linux_desktop_environment(env, logger):
    xdg_current_desktop = env.get("XDG_CURRENT_DESKTOP", None)
    desktop_session = env.get("DESKTOP_SESSION", "")
    if xdg_current_desktop is not None:
        for part in map(str.strip, xdg_current_desktop.split(":")):
            if part == "Unity":
                if "gnome-fallback" in desktop_session:
                    return _LinuxDesktopEnvironment.GNOME
                return _LinuxDesktopEnvironment.UNITY
            elif part == "Deepin":
                return _LinuxDesktopEnvironment.DEEPIN
            elif part == "GNOME":
                return _LinuxDesktopEnvironment.GNOME
            elif part == "X-Cinnamon":
                return _LinuxDesktopEnvironment.CINNAMON
            elif part == "KDE":
                kde_version = env.get("KDE_SESSION_VERSION", None)
                if kde_version == "5":
                    return _LinuxDesktopEnvironment.KDE5
                elif kde_version == "6":
                    return _LinuxDesktopEnvironment.KDE6
                elif kde_version == "4":
                    return _LinuxDesktopEnvironment.KDE4
                logger.info(f'unknown KDE version: "{kde_version}". Assuming KDE4')
                return _LinuxDesktopEnvironment.KDE4
            elif part == "Pantheon":
                return _LinuxDesktopEnvironment.PANTHEON
            elif part == "XFCE":
                return _LinuxDesktopEnvironment.XFCE
            elif part == "UKUI":
                return _LinuxDesktopEnvironment.UKUI
            elif part == "LXQt":
                return _LinuxDesktopEnvironment.LXQT
        logger.debug(f'XDG_CURRENT_DESKTOP is set to an unknown value: "{xdg_current_desktop}"')

    if desktop_session == "deepin":
        return _LinuxDesktopEnvironment.DEEPIN
    elif desktop_session in ("mate", "gnome"):
        return _LinuxDesktopEnvironment.GNOME
    elif desktop_session in ("kde4", "kde-plasma"):
        return _LinuxDesktopEnvironment.KDE4
    elif desktop_session == "kde":
        if "KDE_SESSION_VERSION" in env:
            return _LinuxDesktopEnvironment.KDE4
        return _LinuxDesktopEnvironment.KDE3
    elif "xfce" in desktop_session or desktop_session == "xubuntu":
        return _LinuxDesktopEnvironment.XFCE
    elif desktop_session == "ukui":
        return _LinuxDesktopEnvironment.UKUI
    else:
        logger.debug(f'DESKTOP_SESSION is set to an unknown value: "{desktop_session}"')

    if "GNOME_DESKTOP_SESSION_ID" in env:
        return _LinuxDesktopEnvironment.GNOME
    elif "KDE_FULL_SESSION" in env:
        if "KDE_SESSION_VERSION" in env:
            return _LinuxDesktopEnvironment.KDE4
        return _LinuxDesktopEnvironment.KDE3

    return _LinuxDesktopEnvironment.OTHER


def _choose_linux_keyring(logger):
    desktop_environment = _get_linux_desktop_environment(os.environ, logger)
    logger.debug(f"detected desktop environment: {desktop_environment.name}")
    if desktop_environment == _LinuxDesktopEnvironment.KDE4:
        return _LinuxKeyring.KWALLET
    elif desktop_environment == _LinuxDesktopEnvironment.KDE5:
        return _LinuxKeyring.KWALLET5
    elif desktop_environment == _LinuxDesktopEnvironment.KDE6:
        return _LinuxKeyring.KWALLET6
    elif desktop_environment in (
        _LinuxDesktopEnvironment.KDE3,
        _LinuxDesktopEnvironment.LXQT,
        _LinuxDesktopEnvironment.OTHER,
    ):
        return _LinuxKeyring.BASICTEXT
    return _LinuxKeyring.GNOMEKEYRING


def _get_kwallet_network_wallet(keyring, logger):
    default_wallet = "kdewallet"
    try:
        if keyring == _LinuxKeyring.KWALLET:
            service_name, wallet_path = "org.kde.kwalletd", "/modules/kwalletd"
        elif keyring == _LinuxKeyring.KWALLET5:
            service_name, wallet_path = "org.kde.kwalletd5", "/modules/kwalletd5"
        elif keyring == _LinuxKeyring.KWALLET6:
            service_name, wallet_path = "org.kde.kwalletd6", "/modules/kwalletd6"
        else:
            raise ValueError(keyring)

        proc = subprocess.run(
            ["dbus-send", "--session", "--print-reply=literal", f"--dest={service_name}",
             wallet_path, "org.kde.KWallet.networkWallet"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if proc.returncode:
            logger.warning("failed to read NetworkWallet")
            return default_wallet
        logger.debug(f'NetworkWallet = "{proc.stdout.strip()}"')
        return proc.stdout.strip()
    except Exception as e:
        logger.warning(f"exception while obtaining NetworkWallet: {e}")
        return default_wallet


def _get_kwallet_password(browser_keyring_name, keyring, logger):
    logger.debug(f"using kwallet-query to obtain password from {keyring.name}")
    if shutil.which("kwallet-query") is None:
        logger.error(
            "kwallet-query command not found. KWallet and kwallet-query must be "
            "installed to read from KWallet.")
        return b""

    network_wallet = _get_kwallet_network_wallet(keyring, logger)
    try:
        proc = subprocess.run(
            ["kwallet-query", "--read-password", f"{browser_keyring_name} Safe Storage",
             "--folder", f"{browser_keyring_name} Keys", network_wallet],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if proc.returncode:
            logger.error(f"kwallet-query failed with return code {proc.returncode}.")
            return b""
        if proc.stdout.lower().startswith(b"failed to read"):
            logger.debug("failed to read password from kwallet. Using empty string instead")
            return b""
        logger.debug("password found")
        return proc.stdout.rstrip(b"\n")
    except Exception as e:
        logger.warning(f"exception running kwallet-query: {e}")
        return b""


def _get_gnome_keyring_password(browser_keyring_name, logger):
    if not secretstorage:
        logger.error("secretstorage not available; install the 'secretstorage' package")
        return b""
    with contextlib.closing(secretstorage.dbus_init()) as con:
        col = secretstorage.get_default_collection(con)
        for item in col.get_all_items():
            if item.get_label() == f"{browser_keyring_name} Safe Storage":
                return item.get_secret()
        logger.error("failed to read from keyring")
        return b""


def get_linux_keyring_password(browser_keyring_name, keyring, logger):
    keyring = _LinuxKeyring[keyring] if keyring else _choose_linux_keyring(logger)
    logger.debug(f"Chosen keyring: {keyring.name}")

    if keyring in (_LinuxKeyring.KWALLET, _LinuxKeyring.KWALLET5, _LinuxKeyring.KWALLET6):
        return _get_kwallet_password(browser_keyring_name, keyring, logger)
    elif keyring == _LinuxKeyring.GNOMEKEYRING:
        return _get_gnome_keyring_password(browser_keyring_name, logger)
    elif keyring == _LinuxKeyring.BASICTEXT:
        # basic text: all values are stored as v10 (no keyring password needed)
        return None
    raise AssertionError(f"Unknown keyring {keyring}")


def get_mac_keyring_password(browser_keyring_name, logger):
    logger.debug("using find-generic-password to obtain password from OSX keychain")
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-w",
             "-a", browser_keyring_name,
             "-s", f"{browser_keyring_name} Safe Storage"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if proc.returncode:
            logger.warning("find-generic-password failed")
            return None
        return proc.stdout.rstrip(b"\n")
    except Exception as e:
        logger.warning(f"exception running find-generic-password: {e}")
        return None


def get_windows_v10_key(browser_root, logger):
    path = newest(find_files(browser_root, "Local State"))
    if path is None:
        logger.error("could not find local state file")
        return None
    logger.debug(f'Found local state file at "{path}"')
    with open(path, encoding="utf8") as f:
        data = json.load(f)
    try:
        base64_key = data["os_crypt"]["encrypted_key"]
    except KeyError:
        logger.error("no encrypted key in Local State")
        return None
    encrypted_key = base64.b64decode(base64_key)
    prefix = b"DPAPI"
    if not encrypted_key.startswith(prefix):
        logger.error("invalid key")
        return None
    return _decrypt_windows_dpapi(encrypted_key[len(prefix):], logger)


def _decrypt_windows_dpapi(ciphertext, logger):
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(ciphertext)
    blob_in = DATA_BLOB(ctypes.sizeof(buffer), buffer)
    blob_out = DATA_BLOB()
    ret = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ret:
        raise DecryptionError("Failed to decrypt with DPAPI")

    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return result
