"""Browser detection and on-disk profile enumeration.

The profile-location logic (per-platform ``browser_dir`` maps, Firefox root
dirs, keyring names) is ported from yt-dlp (public domain):
``_get_chromium_based_browser_settings`` and ``_firefox_browser_dirs`` from
``yt_dlp/cookies.py``.

The :class:`Profile` object and :func:`list_profiles` discovery are new: they
turn yt-dlp's "give me a browser name" model into a "enumerate every profile on
disk" model, which every extractor (cookies, history, ...) then consumes.
"""
from __future__ import annotations

import configparser
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ._paths import config_home

CHROMIUM_BASED_BROWSERS = {"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"}
FIREFOX_BASED_BROWSERS = {"firefox"}
SUPPORTED_BROWSERS = CHROMIUM_BASED_BROWSERS | FIREFOX_BASED_BROWSERS

# Browsers that keep their data directly in the user-data dir (no profile subdirs)
_BROWSERS_WITHOUT_PROFILES = {"opera"}


@dataclass
class Profile:
    """A single browser profile discovered on disk.

    ``path`` is the directory holding that profile's data files (Cookies,
    History, ...). For Chromium, ``root`` is the user-data dir (where
    ``Local State`` lives, needed for Windows key extraction) and
    ``keyring_name`` is the OS secret-store service name.
    """

    browser: str
    family: str  # 'chromium' | 'firefox'
    name: str
    path: Path
    root: Path | None = None
    keyring_name: str | None = None

    @property
    def label(self) -> str:
        return f"{self.browser}:{self.name}"


# --------------------------------------------------------------------------- #
# Chromium                                                                     #
# --------------------------------------------------------------------------- #

def _chromium_browser_dir(browser_name: str) -> str:
    if sys.platform in ("cygwin", "win32"):
        appdata_local = os.path.expandvars("%LOCALAPPDATA%")
        appdata_roaming = os.path.expandvars("%APPDATA%")
        return {
            "brave": os.path.join(appdata_local, R"BraveSoftware\Brave-Browser\User Data"),
            "chrome": os.path.join(appdata_local, R"Google\Chrome\User Data"),
            "chromium": os.path.join(appdata_local, R"Chromium\User Data"),
            "edge": os.path.join(appdata_local, R"Microsoft\Edge\User Data"),
            "opera": os.path.join(appdata_roaming, R"Opera Software\Opera Stable"),
            "vivaldi": os.path.join(appdata_local, R"Vivaldi\User Data"),
            "whale": os.path.join(appdata_local, R"Naver\Naver Whale\User Data"),
        }[browser_name]
    elif sys.platform == "darwin":
        appdata = os.path.expanduser("~/Library/Application Support")
        return {
            "brave": os.path.join(appdata, "BraveSoftware/Brave-Browser"),
            "chrome": os.path.join(appdata, "Google/Chrome"),
            "chromium": os.path.join(appdata, "Chromium"),
            "edge": os.path.join(appdata, "Microsoft Edge"),
            "opera": os.path.join(appdata, "com.operasoftware.Opera"),
            "vivaldi": os.path.join(appdata, "Vivaldi"),
            "whale": os.path.join(appdata, "Naver/Whale"),
        }[browser_name]
    else:
        config = config_home()
        return {
            "brave": os.path.join(config, "BraveSoftware/Brave-Browser"),
            "chrome": os.path.join(config, "google-chrome"),
            "chromium": os.path.join(config, "chromium"),
            "edge": os.path.join(config, "microsoft-edge"),
            "opera": os.path.join(config, "opera"),
            "vivaldi": os.path.join(config, "vivaldi"),
            "whale": os.path.join(config, "naver-whale"),
        }[browser_name]


def _chromium_keyring_name(browser_name: str) -> str:
    return {
        "brave": "Brave",
        "chrome": "Chrome",
        "chromium": "Chromium",
        "edge": "Microsoft Edge" if sys.platform == "darwin" else "Chromium",
        "opera": "Opera" if sys.platform == "darwin" else "Chromium",
        "vivaldi": "Vivaldi" if sys.platform == "darwin" else "Chrome",
        "whale": "Whale",
    }[browser_name]


def _chromium_profile_display_names(root: Path) -> dict[str, str]:
    """Map profile-dir name -> user-facing name via ``Local State`` info_cache."""
    try:
        with open(root / "Local State", encoding="utf8") as f:
            info = json.load(f).get("profile", {}).get("info_cache", {})
        return {dirname: meta.get("name", dirname) for dirname, meta in info.items()}
    except (OSError, ValueError):
        return {}


def _list_chromium_profiles(browser_name: str) -> list[Profile]:
    root = Path(_chromium_browser_dir(browser_name))
    if not root.is_dir():
        return []
    keyring_name = _chromium_keyring_name(browser_name)

    if browser_name in _BROWSERS_WITHOUT_PROFILES:
        return [Profile(browser_name, "chromium", "default", root, root=root, keyring_name=keyring_name)]

    display = _chromium_profile_display_names(root)
    profiles = []
    for entry in sorted(root.iterdir()):
        # A real profile dir has a 'Preferences' file; skip 'System Profile' etc.
        if not entry.is_dir() or entry.name == "System Profile":
            continue
        if not (entry / "Preferences").is_file():
            continue
        profiles.append(Profile(
            browser_name, "chromium", display.get(entry.name, entry.name), entry,
            root=root, keyring_name=keyring_name))
    return profiles


# --------------------------------------------------------------------------- #
# Firefox                                                                      #
# --------------------------------------------------------------------------- #

def _firefox_browser_dirs():
    if sys.platform in ("cygwin", "win32"):
        yield from map(os.path.expandvars, (
            R"%APPDATA%\Mozilla\Firefox",
            R"%LOCALAPPDATA%\Packages\Mozilla.Firefox_n80bbvh6b1yt2\LocalCache\Roaming\Mozilla\Firefox",
        ))
    elif sys.platform == "darwin":
        yield os.path.expanduser("~/Library/Application Support/Firefox")
    else:
        yield from map(os.path.expanduser, (
            os.path.join(config_home(), "mozilla/firefox"),
            "~/.mozilla/firefox",
            "~/.var/app/org.mozilla.firefox/config/mozilla/firefox",
            "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
            "~/snap/firefox/common/.mozilla/firefox",
        ))


def _list_firefox_profiles(_browser_name: str = "firefox") -> list[Profile]:
    profiles: list[Profile] = []
    seen: set[Path] = set()
    for root_str in _firefox_browser_dirs():
        root = Path(root_str)
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue
        parser = configparser.ConfigParser()
        try:
            parser.read(ini)
        except configparser.Error:
            continue
        for section in parser.sections():
            if not section.startswith("Profile"):
                continue
            rel = parser.getboolean(section, "IsRelative", fallback=True)
            path_val = parser.get(section, "Path", fallback=None)
            if not path_val:
                continue
            path = (root / path_val) if rel else Path(path_val)
            if not path.is_dir() or path in seen:
                continue
            seen.add(path)
            name = parser.get(section, "Name", fallback=path.name)
            profiles.append(Profile("firefox", "firefox", name, path))
    return profiles


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def list_profiles(browser: str | None = None) -> list[Profile]:
    """Discover every installed browser profile on disk.

    Pass ``browser`` (e.g. ``"chrome"``, ``"firefox"``) to restrict to one.
    Returns an empty list for browsers that are not installed.
    """
    if browser is not None and browser not in SUPPORTED_BROWSERS:
        raise ValueError(f"unsupported browser: {browser!r} (supported: {sorted(SUPPORTED_BROWSERS)})")

    targets = [browser] if browser else sorted(SUPPORTED_BROWSERS)
    out: list[Profile] = []
    for name in targets:
        if name in CHROMIUM_BASED_BROWSERS:
            out.extend(_list_chromium_profiles(name))
        else:
            out.extend(_list_firefox_profiles(name))
    return out
