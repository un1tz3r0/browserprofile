"""Small logging shim.

yt-dlp's cookie code threads a logger object with ``debug/info/warning/error``
methods (and a ``warning(msg, only_once=True)`` de-dup flag) through every
function. We keep that interface so the ported code is unchanged, but back it
with the stdlib ``logging`` module.
"""
from __future__ import annotations

import logging


class Logger:
    """Adapter exposing the ``debug/info/warning/error`` interface the ported
    yt-dlp code expects, including ``warning(..., only_once=True)``."""

    def __init__(self, name: str = "browserprofile", level: int = logging.WARNING):
        self._log = logging.getLogger(name)
        if not self._log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            self._log.addHandler(handler)
        self._log.setLevel(level)
        self._seen: set[str] = set()

    def set_level(self, level: int) -> None:
        self._log.setLevel(level)

    def debug(self, message: str) -> None:
        self._log.debug(message)

    def info(self, message: str) -> None:
        self._log.info(message)

    def warning(self, message: str, *, only_once: bool = False) -> None:
        if only_once:
            if message in self._seen:
                return
            self._seen.add(message)
        self._log.warning(message)

    def error(self, message: str) -> None:
        self._log.error(message)
