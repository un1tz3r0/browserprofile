"""Checkpoint build + diff tests. Pure logic: records are constructed directly,
no browser or profile on disk is read."""
import json

import pytest

import browserprofile as bp
from browserprofile import checkpoint as cp


def _cookie(name="sid", value="abc", host=".example.com", path="/"):
    return bp.Cookie(host=host, name=name, value=value, path=path, secure=True,
                     http_only=False, same_site="Lax", expires=None,
                     browser="chrome", profile="Default")


def _checkpoint(rows, secrets="hash"):
    """A minimal checkpoint dict holding only the given cookie rows."""
    records = {kind: [] for kind in cp._EXTRACTORS}
    records["cookies"] = [cp._apply_secrets("cookies", c.to_dict(), secrets) for c in rows]
    return {"version": cp.VERSION, "created": "t", "sources": ["chrome:Default"],
            "secrets": secrets, "records": records}


def test_hash_hides_value_but_is_deterministic():
    one = cp._apply_secrets("cookies", _cookie(value="secret").to_dict(), "hash")
    two = cp._apply_secrets("cookies", _cookie(value="secret").to_dict(), "hash")
    assert one["value"].startswith("sha256:")
    assert "secret" not in one["value"]
    assert one["value"] == two["value"]  # same value -> same hash, so diffable
    assert one["value"] != cp._apply_secrets("cookies", _cookie(value="other").to_dict(), "hash")["value"]


def test_exclude_drops_value_but_keeps_shape():
    row = cp._apply_secrets("cookies", _cookie(value="secret").to_dict(), "exclude")
    assert row["value"] is None
    assert "value" in row


def test_decrypted_keeps_value():
    row = cp._apply_secrets("cookies", _cookie(value="secret").to_dict(), "decrypted")
    assert row["value"] == "secret"


def test_non_secret_field_is_untouched_in_every_mode():
    for mode in cp.SECRET_MODES:
        row = cp._apply_secrets("cookies", _cookie().to_dict(), mode)
        assert row["host"] == ".example.com"


def test_diff_detects_add_remove_change():
    before = _checkpoint([_cookie(name="keep"), _cookie(name="gone")])
    after = _checkpoint([_cookie(name="keep", value="rotated"), _cookie(name="new")])

    delta = bp.diff_checkpoints(before, after)["cookies"]
    assert {r["name"] for r in delta["added"]} == {"new"}
    assert {r["name"] for r in delta["removed"]} == {"gone"}
    assert len(delta["changed"]) == 1
    assert delta["changed"][0]["key"]["name"] == "keep"
    assert delta["changed"][0]["changed_fields"] == ["value"]


def test_diff_changed_never_reveals_values():
    before = _checkpoint([_cookie(value="old-token")], secrets="decrypted")
    after = _checkpoint([_cookie(value="new-token")], secrets="decrypted")
    changed = bp.diff_checkpoints(before, after)["cookies"]["changed"]
    assert changed[0]["changed_fields"] == ["value"]
    assert "old-token" not in json.dumps(changed)
    assert "new-token" not in json.dumps(changed)


def test_diff_identical_checkpoints_is_empty():
    same = _checkpoint([_cookie()])
    delta = bp.diff_checkpoints(same, same)
    assert all(not any(d.values()) for d in delta.values())


def test_build_rejects_bad_secret_mode():
    with pytest.raises(ValueError):
        bp.build_checkpoint([], secrets="plaintext")


def test_build_with_no_profiles_has_every_kind_empty():
    checkpoint = bp.build_checkpoint([], secrets="hash")
    assert checkpoint["secrets"] == "hash"
    assert set(checkpoint["records"]) == set(cp._EXTRACTORS)
    assert all(rows == [] for rows in checkpoint["records"].values())
