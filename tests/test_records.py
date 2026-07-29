"""Deterministic unit tests for timestamp conversion and samesite mapping."""
import datetime as dt

from browserprofile.cookies import _CHROMIUM_SAMESITE, _FIREFOX_SAMESITE
from browserprofile.records import Cookie, chrome_time, unix_micros, unix_seconds

_JAN_2021 = dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc)


def test_chrome_time_known_value():
    # 2021-01-01 UTC = 13253932800000000 microseconds since 1601-01-01
    assert chrome_time(13253932800000000) == _JAN_2021


def test_unix_micros_known_value():
    assert unix_micros(1609459200000000) == _JAN_2021


def test_unix_seconds_known_value():
    assert unix_seconds(1609459200) == _JAN_2021


def test_zero_and_none_are_none():
    for fn in (chrome_time, unix_micros, unix_seconds):
        assert fn(0) is None
        assert fn(None) is None


def test_samesite_maps():
    assert _CHROMIUM_SAMESITE == {-1: None, 0: "None", 1: "Lax", 2: "Strict"}
    assert _FIREFOX_SAMESITE == {0: "None", 1: "Lax", 2: "Strict"}


def test_record_to_dict_serializes_datetime():
    c = Cookie(
        host=".example.com", name="sid", value="abc", path="/", secure=True,
        http_only=True, same_site="Lax", expires=_JAN_2021,
        browser="chrome", profile="Default")
    d = c.to_dict()
    assert d["expires"] == "2021-01-01T00:00:00+00:00"
    assert d["secure"] is True
    assert d["host"] == ".example.com"
