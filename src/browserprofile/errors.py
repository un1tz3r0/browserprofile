"""Exception types for browserprofile."""
from __future__ import annotations


class BrowserProfileError(Exception):
    """Base class for all browserprofile errors."""


class ProfileNotFoundError(BrowserProfileError):
    """A requested browser profile / data file could not be located."""


class DecryptionError(BrowserProfileError):
    """A value could not be decrypted (missing key, wrong platform, etc.)."""
