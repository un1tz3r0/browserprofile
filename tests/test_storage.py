"""Site-storage copy tests, using a fake profile directory (no browser needed)."""
import shutil
import types

import pytest

import browserprofile as bp
from browserprofile import storage
from browserprofile.errors import BrowserProfileError


def _profile(path, family="chromium"):
    return bp.Profile("chrome", family, "Default", path)


def _patch_copytree(monkeypatch, copytree):
    # Swap storage's view of shutil only: copytree recurses through the real
    # module's attribute, so patching that would hook every subdirectory too.
    monkeypatch.setattr(storage, "shutil", types.SimpleNamespace(
        copytree=copytree, ignore_patterns=shutil.ignore_patterns,
        rmtree=shutil.rmtree, Error=shutil.Error))


def _seed(path):
    leveldb = path / "Local Storage" / "leveldb"
    leveldb.mkdir(parents=True)
    (leveldb / "000003.log").write_text("ls")
    (leveldb / "LOCK").write_text("")
    blob = path / "IndexedDB" / "https_example.com_0.indexeddb.blob"
    blob.mkdir(parents=True)
    (blob / "1").write_text("idb")
    (blob.parent / "LOCK").write_text("")


def test_copies_storage_without_locks(tmp_path):
    src = tmp_path / "src"
    _seed(src)
    dest = tmp_path / "out" / "Default"

    copied = bp.copy_site_storage(_profile(src), dest)

    assert copied == [dest / "Local Storage", dest / "IndexedDB"]
    assert (dest / "Local Storage" / "leveldb" / "000003.log").read_text() == "ls"
    assert (dest / "IndexedDB" / "https_example.com_0.indexeddb.blob" / "1").read_text() == "idb"
    assert not list(dest.rglob("LOCK"))


def test_unused_storage_is_skipped(tmp_path):
    src = tmp_path / "src"
    (src / "Local Storage").mkdir(parents=True)
    dest = tmp_path / "dest"

    assert bp.copy_site_storage(_profile(src), dest) == [dest / "Local Storage"]


def test_firefox_rejected(tmp_path):
    with pytest.raises(BrowserProfileError):
        bp.copy_site_storage(_profile(tmp_path, family="firefox"), tmp_path / "dest")


def test_existing_destination_is_left_alone(tmp_path):
    src = tmp_path / "src"
    _seed(src)
    existing = tmp_path / "dest" / "Local Storage" / "precious"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep")

    with pytest.raises(FileExistsError):
        bp.copy_site_storage(_profile(src), tmp_path / "dest")
    assert existing.read_text() == "keep"


def test_retries_when_file_set_changes_during_copy(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _seed(src)
    calls = []

    def compacting_copytree(source, target, **kwargs):
        result = shutil.copytree(source, target, **kwargs)
        calls.append(source)
        if len(calls) == 1:  # a compaction lands right after the first copy
            (source / "leveldb" / "000004.ldb").write_text("compacted")
        return result

    _patch_copytree(monkeypatch, compacting_copytree)
    dest = tmp_path / "dest"
    bp.copy_site_storage(_profile(src), dest)

    assert len(calls) == 3  # Local Storage twice, IndexedDB once
    assert (dest / "Local Storage" / "leveldb" / "000004.ldb").read_text() == "compacted"


def test_retries_when_a_file_vanishes_during_copy(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _seed(src)
    calls = []

    def vanishing_copytree(source, target, **kwargs):
        calls.append(source)
        result = shutil.copytree(source, target, **kwargs)
        if len(calls) == 1:
            raise shutil.Error([("a", "b", "vanished")])
        return result

    _patch_copytree(monkeypatch, vanishing_copytree)
    dest = tmp_path / "dest"
    bp.copy_site_storage(_profile(src), dest)

    assert (dest / "Local Storage" / "leveldb" / "000003.log").read_text() == "ls"


def test_gives_up_when_source_never_settles(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _seed(src)
    calls = []

    def churning_copytree(source, target, **kwargs):
        calls.append(source)
        result = shutil.copytree(source, target, **kwargs)
        (source / f"{len(calls)}.ldb").write_text("")
        return result

    _patch_copytree(monkeypatch, churning_copytree)

    with pytest.raises(BrowserProfileError, match="kept changing"):
        bp.copy_site_storage(_profile(src), tmp_path / "dest")
    assert not (tmp_path / "dest" / "Local Storage").exists()
