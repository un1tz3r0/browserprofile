"""On-disk site storage (localStorage / IndexedDB) for Chromium profiles.

Unlike cookies and passwords, these aren't encrypted with the OS key, so a
downstream consumer can seed another profile by copying the directories as-is.
There's no record-level extraction here: reading them would mean parsing
LevelDB, Snappy and V8-serialized values.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .errors import BrowserProfileError
from .profiles import Profile

_CHROMIUM_STORAGE_DIRS = ("Local Storage", "IndexedDB")
# LevelDB compaction can rewrite the file set mid-copy when the browser is running
_COPY_ATTEMPTS = 5


def _file_names(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*")}


def _copy_stable(source: Path, target: Path) -> None:
    """Copy ``source`` to ``target``, retrying until the file set held still.

    Only added/removed files count as a change: growth of a LevelDB ``.log`` is
    harmless because LevelDB recovers from a truncated log. ``LOCK`` is the
    running browser's and isn't copied.
    """
    for _ in range(_COPY_ATTEMPTS):
        before = _file_names(source)
        try:
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("LOCK"))
            if _file_names(source) == before:
                return
        except shutil.Error:  # a file vanished while being copied
            pass
        shutil.rmtree(target)
    raise BrowserProfileError(f'"{source}" kept changing while being copied')


def copy_site_storage(profile: Profile, dest: str | Path) -> list[Path]:
    """Copy a Chromium profile's localStorage and IndexedDB into ``dest``.

    ``dest`` is the target profile directory (e.g. ``<user-data-dir>/Default``)
    and must not already contain them. Safe to call while the browser is
    running. Returns the directories created; a storage type the profile has
    never used is skipped.
    """
    if profile.family != "chromium":
        raise BrowserProfileError(f"site storage copy is not supported for {profile.family}")

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in _CHROMIUM_STORAGE_DIRS:
        source = profile.path / name
        if source.is_dir():
            _copy_stable(source, dest / name)
            copied.append(dest / name)
    return copied
