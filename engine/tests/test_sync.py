"""Team sync client: the merge rule and the secret guard.

The Worker's own conflict semantics are exercised against a real `wrangler dev`
instance (see cloud/README.md); these cover the client half, which is where a
wrong decision loses someone's local edit.
"""

import time

import pytest

from qwerty import sync as sync_mod
from qwerty.server import DashboardStore, normalize_dashboard_profile
from qwerty.store import ProfileStore


def _machine(tmp_path, name):
    store = ProfileStore(tmp_path / name)
    return store, DashboardStore(store.root)


def _profile(pid, name, updated_at, **extra):
    return normalize_dashboard_profile(
        {"id": pid, "name": name, "os": "Windows", "updated_at": updated_at, **extra})


# --- the secret guard -------------------------------------------------------

def test_push_refuses_a_plaintext_proxy_password(tmp_path):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "has-secret", time.time(),
                       proxy={"host": "1.2.3.4", "port": "8080", "pass": "PLAINTEXT"}))
    sync_mod.set_config(store, "http://example.invalid", "tok")

    with pytest.raises(sync_mod.SyncError, match="unencrypted proxy password"):
        sync_mod.push(store, dash, dry_run=True)


def test_an_encrypted_secret_is_allowed(tmp_path):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "ok", time.time(),
                       proxy={"host": "1.2.3.4", "port": "8080", "pass": "enc:v1:abc"}))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    assert sync_mod.push(store, dash, dry_run=True)["pushed"] == 1


def test_no_proxy_at_all_is_allowed(tmp_path):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "direct", time.time()))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    assert sync_mod.push(store, dash, dry_run=True)["pushed"] == 1


# --- what crosses the wire --------------------------------------------------

def test_machine_local_fields_are_never_uploaded():
    p = _profile("p1", "x", 100, status="running", lastActive="now")
    p["_activity"] = [{"kind": "launch"}]
    p["_session"] = {"status": "ok"}
    scrubbed = sync_mod.scrub(p)
    for field in sync_mod.LOCAL_ONLY:
        assert field not in scrubbed
    assert scrubbed["name"] == "x", "real config must survive the scrub"


# --- last-write-wins on pull ------------------------------------------------

def _fake_pull(monkeypatch, payload):
    monkeypatch.setattr(sync_mod, "_request", lambda *a, **k: payload)


def test_pull_does_not_clobber_a_newer_local_edit(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "local-newer", 500))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    _fake_pull(monkeypatch, {"profiles": [_profile("p1", "remote-older", 100)],
                             "deleted": [], "now": 999})

    res = sync_mod.pull(store, dash)
    assert res["skipped"] == ["p1"] and res["applied"] == []
    assert dash.get("p1")["name"] == "local-newer"


def test_pull_applies_a_newer_remote_edit(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "local-older", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    _fake_pull(monkeypatch, {"profiles": [_profile("p1", "remote-newer", 500)],
                             "deleted": [], "now": 999})

    assert sync_mod.pull(store, dash)["applied"] == ["p1"]
    assert dash.get("p1")["name"] == "remote-newer"


def test_pull_keeps_this_machines_own_view(tmp_path, monkeypatch):
    """A remote edit must not import another machine's run state."""
    store, dash = _machine(tmp_path, "m1")
    mine = _profile("p1", "old", 100)
    mine["_activity"] = [{"kind": "launch", "detail": "local"}]
    dash.save(mine)
    sync_mod.set_config(store, "http://example.invalid", "tok")
    _fake_pull(monkeypatch, {"profiles": [_profile("p1", "new", 500)],
                             "deleted": [], "now": 999})

    sync_mod.pull(store, dash)
    got = dash.get("p1")
    assert got["name"] == "new", "config came across"
    assert got["_activity"] == [{"kind": "launch", "detail": "local"}], "local history stayed"


def test_pull_applies_tombstones_and_advances_the_cursor(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("gone", "doomed", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    _fake_pull(monkeypatch, {"profiles": [], "deleted": ["gone", "never-had-it"], "now": 4242})

    res = sync_mod.pull(store, dash)
    assert res["deleted"] == ["gone"], "an unknown id is not an error"
    assert dash.get("gone") is None
    assert sync_mod.get_config(store)["cursor"] == 4242


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "local", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    _fake_pull(monkeypatch, {"profiles": [_profile("p1", "remote", 500)],
                             "deleted": [], "now": 999})

    sync_mod.pull(store, dash, dry_run=True)
    assert dash.get("p1")["name"] == "local"
    assert sync_mod.get_config(store)["cursor"] == 0, "cursor must not advance on a dry run"


# --- configuration ----------------------------------------------------------

def test_login_keeps_the_cursor_when_only_the_token_rotates(tmp_path):
    store, _ = _machine(tmp_path, "m1")
    sync_mod.set_config(store, "https://a.example", "old")
    store.save_config({**store.get_config(), "sync": {**sync_mod.get_config(store), "cursor": 77}})

    assert sync_mod.set_config(store, "https://a.example", "new")["cursor"] == 77
    # A different server is a different timeline — start over.
    assert sync_mod.set_config(store, "https://b.example", "new")["cursor"] == 0


def test_an_unconfigured_remote_is_refused_not_crashed(tmp_path):
    store, dash = _machine(tmp_path, "m1")
    assert sync_mod.get_config(store) is None
    assert sync_mod.status(store, dash)["configured"] is False
    for call in (sync_mod.push, sync_mod.pull):
        with pytest.raises(sync_mod.SyncError, match="no remote configured"):
            call(store, dash)


# --- incremental push -------------------------------------------------------
# A full push costs one D1 row read per profile per push, even when nothing
# changed: the server's upsert reads the existing row to evaluate its
# updated_at guard. Across a team that is users x pushes x profiles reads a
# day, and the pool grows with the team. These pin the watermark that avoids it.

def _sent(monkeypatch):
    """Capture the bodies push() actually puts on the wire."""
    calls = []

    def fake(cfg, method, path, body=None, timeout=30):
        calls.append(body)
        return {"ok": True, "pushed": len(body.get("profiles", [])), "at": 12345}

    monkeypatch.setattr(sync_mod, "_request", fake)
    return calls


def test_a_second_push_with_no_edits_sends_nothing(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "a", 100))
    dash.save(_profile("p2", "b", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    calls = _sent(monkeypatch)

    first = sync_mod.push(store, dash)
    assert first["pushed"] == 2 and len(calls) == 1

    second = sync_mod.push(store, dash)
    assert second["pushed"] == 0 and second["skipped"] == 2
    assert len(calls) == 1, "an empty push must not even make the request"


def test_only_the_edited_profile_is_resent(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "a", 100))
    dash.save(_profile("p2", "b", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    calls = _sent(monkeypatch)
    sync_mod.push(store, dash)

    dash.save(_profile("p2", "b-edited", 500))
    res = sync_mod.push(store, dash)

    assert res["pushed"] == 1 and res["skipped"] == 1
    assert [p["id"] for p in calls[-1]["profiles"]] == ["p2"]


def test_all_forces_a_full_resend(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "a", 100))
    dash.save(_profile("p2", "b", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    calls = _sent(monkeypatch)
    sync_mod.push(store, dash)

    res = sync_mod.push(store, dash, everything=True)
    assert res["pushed"] == 2
    assert {p["id"] for p in calls[-1]["profiles"]} == {"p1", "p2"}


def test_a_failed_push_does_not_advance_the_watermark(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "a", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")

    def boom(*a, **k):
        raise sync_mod.SyncError("server down")

    monkeypatch.setattr(sync_mod, "_request", boom)
    with pytest.raises(sync_mod.SyncError):
        sync_mod.push(store, dash)
    assert sync_mod.get_config(store).get("pushed", 0) == 0

    # Once the server is back, the profile is still pending.
    calls = _sent(monkeypatch)
    assert sync_mod.push(store, dash)["pushed"] == 1
    assert [p["id"] for p in calls[-1]["profiles"]] == ["p1"]


def test_a_dry_run_does_not_advance_the_watermark(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "a", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    calls = _sent(monkeypatch)

    assert sync_mod.push(store, dash, dry_run=True)["pushed"] == 1
    assert calls == [], "a dry run must not send anything"
    assert sync_mod.push(store, dash)["pushed"] == 1, "still pending after a dry run"


def test_a_pulled_profile_is_not_echoed_back(tmp_path, monkeypatch):
    """Without this the next push returns every pulled profile to its origin."""
    store, dash = _machine(tmp_path, "m1")
    sync_mod.set_config(store, "http://example.invalid", "tok")
    monkeypatch.setattr(sync_mod, "_request",
                        lambda *a, **k: {"profiles": [_profile("remote", "r", 900)],
                                         "deleted": [], "now": 50})
    sync_mod.pull(store, dash)
    assert dash.get("remote") is not None

    calls = _sent(monkeypatch)
    res = sync_mod.push(store, dash)
    assert res["pushed"] == 0, "a just-pulled profile must not be sent straight back"
    assert calls == []


def test_only_outgoing_profiles_are_secret_checked(tmp_path, monkeypatch):
    """An already-pushed plaintext secret must not block unrelated later pushes.

    (It was still refused on the push that would have uploaded it — see
    test_push_refuses_a_plaintext_proxy_password.)
    """
    store, dash = _machine(tmp_path, "m1")
    sync_mod.set_config(store, "http://example.invalid", "tok")
    _sent(monkeypatch)
    dash.save(_profile("clean", "ok", 100))
    sync_mod.push(store, dash)

    # An old profile with a bad secret, untouched since before the watermark.
    dash.save(_profile("legacy", "bad", 50,
                       proxy={"host": "1.2.3.4", "port": "8080", "pass": "PLAINTEXT"}))
    dash.save(_profile("new", "fine", 500))
    assert sync_mod.push(store, dash)["pushed"] == 1


def test_switching_servers_resets_the_watermark(tmp_path):
    store, _ = _machine(tmp_path, "m1")
    sync_mod.set_config(store, "https://a.example", "tok")
    _save = store.get_config()
    _save["sync"]["pushed"] = 999
    store.save_config(_save)

    assert sync_mod.set_config(store, "https://a.example", "tok2")["pushed"] == 999
    assert sync_mod.set_config(store, "https://b.example", "tok2")["pushed"] == 0


def test_status_counts_what_is_pending(tmp_path, monkeypatch):
    store, dash = _machine(tmp_path, "m1")
    dash.save(_profile("p1", "a", 100))
    dash.save(_profile("p2", "b", 100))
    sync_mod.set_config(store, "http://example.invalid", "tok")
    _sent(monkeypatch)

    monkeypatch.setattr(sync_mod, "whoami", lambda cfg: {"name": "me"})
    assert sync_mod.status(store, dash)["unpushed"] == 2
    sync_mod.push(store, dash)
    assert sync_mod.status(store, dash)["unpushed"] == 0
    dash.save(_profile("p2", "b2", 700))
    assert sync_mod.status(store, dash)["unpushed"] == 1
