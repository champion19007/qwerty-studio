"""Backup/restore round-trips a profile *and* its browser session (user-data)."""

from pathlib import Path

import pytest

from qwerty.fingerprint import generate
from qwerty.models import Profile
from qwerty.store import ProfileStore


def _seed_profile(store, name="Acct"):
    prof = store.save(Profile(name=name, fingerprint=generate(os="windows", seed=7)))
    # Simulate a browser session on disk (cookies, localStorage, …).
    ud = store.user_data_path(prof.id)
    (ud / "Default").mkdir(parents=True, exist_ok=True)
    (ud / "Default" / "Cookies").write_bytes(b"session-bytes")
    return prof


def test_backup_then_restore_brings_back_profile_and_session(tmp_path):
    src = ProfileStore(tmp_path / "a")
    prof = _seed_profile(src)
    archive = tmp_path / "acct.zip"
    assert src.backup(prof.id, archive) == archive
    assert archive.exists()

    # Restore into a completely separate data dir.
    dst = ProfileStore(tmp_path / "b")
    restored = dst.restore(archive)
    assert restored.id == prof.id and restored.name == "Acct"
    got = dst.get(prof.id)
    assert got is not None and got.fingerprint.seed == 7
    assert (dst.user_data_path(prof.id) / "Default" / "Cookies").read_bytes() == b"session-bytes"


def test_backup_missing_profile_returns_none(tmp_path):
    store = ProfileStore(tmp_path)
    assert store.backup("nope", tmp_path / "x.zip") is None


def test_restore_with_new_id_makes_a_copy(tmp_path):
    src = ProfileStore(tmp_path / "a")
    prof = _seed_profile(src)
    archive = tmp_path / "acct.zip"
    src.backup(prof.id, archive)

    copy = src.restore(archive, new_id=True)
    assert copy.id != prof.id                       # a fresh identity slot
    # Both the original and the copy now exist, each with its own session.
    assert {p.id for p in src.list()} >= {prof.id, copy.id}
    assert (src.user_data_path(copy.id) / "Default" / "Cookies").read_bytes() == b"session-bytes"


# --- hostile archives -------------------------------------------------------
# A backup is designed to be carried between machines, so restore() has to treat
# the zip as untrusted: a crafted entry must not write outside the profile dir.

def _hostile_archive(path, member, payload=b"pwned"):
    """A structurally valid backup whose user-data entry escapes the target."""
    import json, zipfile
    from qwerty.models import Profile
    prof = Profile(name="Evil", fingerprint=generate(os="windows", seed=1))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("profile.json", json.dumps(prof.to_dict()))
        z.writestr(f"user-data/{member}", payload)
    return path


def test_restore_rejects_path_traversal(tmp_path):
    from qwerty.store import UnsafeArchive
    store = ProfileStore(tmp_path / "data")
    archive = _hostile_archive(tmp_path / "evil.zip", "../../../../escaped.txt")

    with pytest.raises(UnsafeArchive):
        store.restore(archive)
    # Nothing was written anywhere outside the store.
    assert not (tmp_path / "escaped.txt").exists()
    assert not (Path.home() / "escaped.txt").exists()


def test_restore_rejects_absolute_paths(tmp_path):
    from qwerty.store import UnsafeArchive
    store = ProfileStore(tmp_path / "data")
    archive = _hostile_archive(tmp_path / "evil2.zip", "/tmp/escaped.txt")
    with pytest.raises(UnsafeArchive):
        store.restore(archive)


def test_restore_aborts_before_writing_any_file(tmp_path):
    """One bad entry must abort the whole restore, not extract the good ones first."""
    import json, zipfile
    from qwerty.store import UnsafeArchive
    store = ProfileStore(tmp_path / "data")
    prof = Profile(name="Mixed", fingerprint=generate(os="windows", seed=2))
    archive = tmp_path / "mixed.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("profile.json", json.dumps(prof.to_dict()))
        z.writestr("user-data/Default/Cookies", b"good")
        z.writestr("user-data/../../escaped.txt", b"bad")

    with pytest.raises(UnsafeArchive):
        store.restore(archive)
    assert not (store.userdata_dir / prof.id / "Default" / "Cookies").exists()


def test_restore_still_accepts_nested_legitimate_paths(tmp_path):
    """The guard must not break ordinary deep session paths."""
    import json, zipfile
    store = ProfileStore(tmp_path / "data")
    prof = Profile(name="Deep", fingerprint=generate(os="windows", seed=3))
    archive = tmp_path / "deep.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("profile.json", json.dumps(prof.to_dict()))
        z.writestr("user-data/Default/Local Storage/leveldb/000003.log", b"ok")

    restored = store.restore(archive)
    got = store.user_data_path(restored.id) / "Default" / "Local Storage" / "leveldb" / "000003.log"
    assert got.read_bytes() == b"ok"
