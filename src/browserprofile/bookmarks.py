"""Bookmark extraction (Chromium + Firefox).

  * Chromium: bookmarks are a JSON file (``Bookmarks``), not SQLite. We walk the
    ``roots`` tree recursively, tracking folder path.
  * Firefox: ``places.sqlite``, ``moz_bookmarks`` (type 1 = bookmark) joined to
    ``moz_places`` for the URL; folder path reconstructed from the parent chain.
"""
from __future__ import annotations

import json

from ._paths import find_files, newest, open_database_copy
from .errors import ProfileNotFoundError
from .logger import Logger
from .profiles import Profile
from .records import Bookmark, chrome_time, unix_micros


def extract_bookmarks(profile: Profile, logger: Logger | None = None, keyring: str | None = None) -> list[Bookmark]:
    logger = logger or Logger()  # keyring is unused (bookmarks are plaintext); kept for a uniform interface
    if profile.family == "chromium":
        return _extract_chromium(profile)
    return _extract_firefox(profile)


def _walk_chromium(node, folder, browser, profile_name, out):
    node_type = node.get("type")
    if node_type == "url":
        out.append(Bookmark(
            title=node.get("name", ""), url=node.get("url", ""), folder=folder,
            date_added=chrome_time(int(node["date_added"])) if node.get("date_added") else None,
            browser=browser, profile=profile_name))
    elif node_type == "folder":
        child_folder = f"{folder}/{node.get('name', '')}" if folder else node.get("name", "")
        for child in node.get("children", []):
            _walk_chromium(child, child_folder, browser, profile_name, out)


def _extract_chromium(profile: Profile) -> list[Bookmark]:
    path = newest(find_files(str(profile.path), "Bookmarks"))
    if path is None:
        raise ProfileNotFoundError(f'no Bookmarks file under "{profile.path}"')

    with open(path, encoding="utf8") as f:
        data = json.load(f)
    out: list[Bookmark] = []
    for root_name, root in data.get("roots", {}).items():
        if isinstance(root, dict):
            _walk_chromium(root, "", profile.browser, profile.name, out)
    return out


def _extract_firefox(profile: Profile) -> list[Bookmark]:
    db_path = newest(find_files(str(profile.path), "places.sqlite"))
    if db_path is None:
        raise ProfileNotFoundError(f'no places.sqlite under "{profile.path}"')

    out: list[Bookmark] = []
    with open_database_copy(db_path) as cursor:
        # parent-id -> title, to reconstruct folder paths
        folders = {row[0]: row[1] or "" for row in cursor.execute(
            "SELECT id, title FROM moz_bookmarks WHERE type = 2").fetchall()}
        parents = dict(cursor.execute("SELECT id, parent FROM moz_bookmarks").fetchall())

        def folder_path(bookmark_id):
            parts = []
            pid = parents.get(bookmark_id)
            while pid and pid in folders:
                if folders[pid]:
                    parts.append(folders[pid])
                pid = parents.get(pid)
            return "/".join(reversed(parts))

        cursor.execute(
            "SELECT b.id, b.title, p.url, b.dateAdded FROM moz_bookmarks b "
            "JOIN moz_places p ON b.fk = p.id WHERE b.type = 1")
        for bid, title, url, date_added in cursor.fetchall():
            out.append(Bookmark(
                title=title or "", url=url, folder=folder_path(bid),
                date_added=unix_micros(date_added),
                browser=profile.browser, profile=profile.name))
    return out
