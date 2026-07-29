"""Smoke tests that don't depend on any browser being installed."""
import browserprofile as bp


def test_list_profiles_runs():
    # Should never raise, regardless of which browsers exist on the machine.
    profiles = bp.list_profiles()
    assert isinstance(profiles, list)
    for p in profiles:
        assert p.family in ("chromium", "firefox")
        assert p.path.exists()


def test_unsupported_browser_rejected():
    import pytest
    with pytest.raises(ValueError):
        bp.list_profiles("netscape")


def test_public_api_exports():
    for name in ("extract_cookies", "extract_history", "extract_bookmarks",
                 "extract_autofill", "extract_logins", "extract_credit_cards"):
        assert callable(getattr(bp, name))
