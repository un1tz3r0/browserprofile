"""browserprofile — detect local browser profiles and extract their on-disk data.

Core profile detection, location and cookie decryption are ported from yt-dlp
(public domain / Unlicense) and extended with history, bookmarks, autofill and
saved-password/credit-card extractors for both Chromium-based browsers and
Firefox.

Typical use::

    import browserprofile as bp

    for profile in bp.list_profiles():
        print(profile.label)
        for entry in bp.extract_history(profile):
            print(entry.last_visit, entry.url)
"""
from __future__ import annotations

from .autofill import extract_autofill
from .bookmarks import extract_bookmarks
from .cookies import extract_cookies
from .errors import BrowserProfileError, DecryptionError, ProfileNotFoundError
from .history import extract_history
from .logger import Logger
from .passwords import extract_credit_cards, extract_logins
from .profiles import (
    CHROMIUM_BASED_BROWSERS,
    SUPPORTED_BROWSERS,
    Profile,
    list_profiles,
)
from .records import (
    AutofillEntry,
    Bookmark,
    Cookie,
    CreditCard,
    HistoryEntry,
    Login,
)

__all__ = [
    "list_profiles",
    "Profile",
    "SUPPORTED_BROWSERS",
    "CHROMIUM_BASED_BROWSERS",
    "extract_cookies",
    "extract_history",
    "extract_bookmarks",
    "extract_autofill",
    "extract_logins",
    "extract_credit_cards",
    "Cookie",
    "HistoryEntry",
    "Bookmark",
    "AutofillEntry",
    "Login",
    "CreditCard",
    "Logger",
    "BrowserProfileError",
    "ProfileNotFoundError",
    "DecryptionError",
]
