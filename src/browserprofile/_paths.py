"""Filesystem / SQLite helpers.

Ported from yt-dlp (public domain): ``_config_home``, ``_open_database_copy``,
``_get_column_names``, ``_newest``, ``_find_files``, ``_is_path`` from
``yt_dlp/cookies.py``. The progress-bar plumbing yt-dlp wraps around
``_find_files`` is dropped.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator


def config_home() -> str:
    return os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))


def expand_path(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def is_path(value: str) -> bool:
    return any(sep in value for sep in (os.path.sep, os.path.altsep) if sep)


def newest(files: Iterator[str] | list[str]) -> str | None:
    return max(files, key=lambda path: os.lstat(path).st_mtime, default=None)


def find_files(root: str, filename: str) -> Iterator[str]:
    """Yield every ``filename`` found anywhere under ``root`` (browsers keep a
    profile's data files in nested dirs)."""
    for curr_root, _, files in os.walk(root):
        for file in files:
            if file == filename:
                yield os.path.join(curr_root, file)


def get_column_names(cursor, table_name: str) -> list[str]:
    table_info = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1].decode() if isinstance(row[1], bytes) else row[1] for row in table_info]


@contextlib.contextmanager
def open_database_copy(database_path: str) -> Iterator[sqlite3.Cursor]:
    """Copy the DB to a temp dir and yield a cursor.

    The browser holds a lock on the live file, so we work on a copy (yt-dlp's
    ``_open_database_copy``). The connection is closed and the temp dir removed
    on exit.
    """
    with tempfile.TemporaryDirectory(prefix="browserprofile") as tmpdir:
        database_copy_path = os.path.join(tmpdir, "temporary.sqlite")
        shutil.copy(database_path, database_copy_path)
        conn = sqlite3.connect(database_copy_path)
        try:
            yield conn.cursor()
        finally:
            conn.close()
