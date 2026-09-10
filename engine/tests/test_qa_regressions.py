"""Regressions for the QA pass — each of these fails against the pre-fix code.

Grouped by the defect they pin down rather than by module, so a failure here
names the bug that came back.
"""

import json
import threading
import time

import pytest

from qwerty import cookies as cookies_mod
from qwerty.bulk import generate_profiles, select
from qwerty.fingerprint import generate, platform_token, rebuild_user_agent
from qwerty.importers import _parse_proxy
from qwerty.models import Profile
from qwerty.proxypool import _proxy_url, parse_line
from qwerty.scheduler import ScheduleStore
from qwerty.store import ProfileStore


# --- one unreadable file must not hide every other profile ------------------

def _seed(store, *names):
    for n in names:
        store.save(Profile(name=n, fingerprint=generate(os="windows", seed=1)))


def test_list_survives_a_profile_missing_a_required_field(tmp_path):
    store = ProfileStore(tmp_path)
    _seed(store, "alpha", "beta", "gamma")
    victim = sorted(store.profiles_dir.glob("*.json"))[0]
    data = json.loads(victim.read_text(encoding="utf-8"))
    del data["fingerprint"]["user_agent"]          # -> TypeError from the dataclass
    victim.write_text(json.dumps(data), encoding="utf-8")

    names = [p.name for p in store.list()]
    assert len(names) == 2, "one bad file must not take the whole listing down"


def test_list_survives_a_wrong_typed_field(tmp_path):
    store = ProfileStore(tmp_path)
    _seed(store, "alpha", "beta")
    victim = sorted(store.profiles_dir.glob("*.json"))[0]
    data = json.loads(victim.read_text(encoding="utf-8"))
    data["fingerprint"] = "not-a-dict"             # -> TypeError/ValueError
    victim.write_text(json.dumps(data), encoding="utf-8")
    assert len(store.list()) == 1


def test_list_with_errors_reports_what_it_skipped(tmp_path):
    store = ProfileStore(tmp_path)
    _seed(store, "alpha")
    (store.profiles_dir / "broken.json").write_text("{not json", encoding="utf-8")

    profiles, skipped = store.list_with_errors()
    assert [p.name for p in profiles] == ["alpha"]
    assert len(skipped) == 1
    assert skipped[0]["file"] == "broken.json"
    assert "JSONDecodeError" in skipped[0]["error"]


# --- concurrent schedule writes must not clobber each other -----------------

def test_concurrent_schedule_writes_lose_nothing(tmp_path):
    store = ScheduleStore(tmp_path)
    ids = [store.add(profile_id="p%d" % i, every_hours=1, now=time.time())["id"]
           for i in range(20)]

    def mark():
        for i in ids:
            store.mark_run(i, time.time())

    def add():
        other = ScheduleStore(tmp_path)            # a different instance, same file
        for i in range(20, 40):
            other.add(profile_id="p%d" % i, every_hours=1, now=time.time())

    threads = [threading.Thread(target=mark), threading.Thread(target=add)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.list()) == 40
    assert all(s.get("lastRun") for s in store.list() if s["id"] in ids)


def test_schedule_update_cannot_rewrite_the_id(tmp_path):
    store = ScheduleStore(tmp_path)
    sid = store.add(profile_id="p1", every_hours=1, now=time.time())["id"]
    store.update(sid, {"id": "hijacked", "minutes": 9})
    assert store.get(sid)["minutes"] == 9
    assert store.get("hijacked") is None


def test_schedules_file_is_never_left_torn(tmp_path):
    store = ScheduleStore(tmp_path)
    for i in range(5):
        store.add(profile_id="p%d" % i, every_hours=1, now=time.time())
    # Whatever is on disk must always be parseable as the whole list.
    assert len(json.loads(store.path.read_text(encoding="utf-8"))) == 5


# --- an Android UA must keep naming the handset it describes -----------------

def test_pinned_chrome_version_keeps_each_handset():
    """Pinning a Chrome version must not reset every phone to the default model."""
    from qwerty import devices

    ps = generate_profiles(20, oses=["android"], chrome_versions=["125.0.0.0"], seed=42)
    assert all(p.fingerprint.chrome_version == "125.0.0.0" for p in ps)
    assert len({p.fingerprint.user_agent for p in ps}) > 1, \
        "every profile claiming one handset is a mass UA collision"

    # The real invariant: the model named in the UA is the phone whose screen,
    # GPU, cores and RAM this profile actually carries.
    by_model = {d["model"]: d for d in devices.ANDROID_DEVICES}
    for p in ps:
        fp = p.fingerprint
        model = platform_token(fp.user_agent).split("; ")[-1]
        d = by_model[model]
        assert (fp.screen_width, fp.screen_height) == d["screen"]
        assert fp.webgl_renderer == d["webgl"][1]
        assert (fp.hardware_concurrency, fp.device_memory) == (d["cores"], d["memory"])


def test_rebuild_user_agent_preserves_token_and_drops_it_on_os_change():
    fp = generate(os="android", seed=9)
    token = platform_token(fp.user_agent)
    assert "Android" in token
    assert platform_token(rebuild_user_agent(fp, "999.0.0.0")) == token
    assert "Chrome/999.0.0.0" in rebuild_user_agent(fp, "999.0.0.0")
    # Changing OS invalidates the token — it described the old device.
    assert platform_token(rebuild_user_agent(fp, "999.0.0.0", os_key="windows")) == \
        "Windows NT 10.0; Win64; x64"


@pytest.mark.parametrize("ua", ["no parens here", "", None])
def test_platform_token_handles_a_ua_without_parentheses(ua):
    assert platform_token(ua) is None


# --- one unparseable cookie must not abort an import ------------------------

@pytest.mark.parametrize("value,expected", [
    ("2026-01-01T00:00:00Z", 1767225600.0),   # ISO -> real timestamp
    ("whenever", -1.0),                       # unparseable -> session cookie
    ("Infinity", -1.0),                       # non-finite -> session cookie
    ("1893456000", 1893456000.0),             # numeric string
    (None, -1.0),
])
def test_cookie_expiry_is_coerced_not_raised(value, expected):
    c = cookies_mod.normalize({"name": "a", "domain": ".x.com", "expirationDate": value})
    assert c is not None and c["expires"] == expected


def test_one_bad_cookie_does_not_abort_the_batch():
    blob = json.dumps([
        {"name": "good", "domain": ".x.com", "expires": 1893456000},
        {"name": "bad", "domain": ".x.com", "expirationDate": "2026-01-01T00:00:00Z"},
        {"name": "also_good", "domain": ".y.com", "expires": 1893456000},
    ])
    assert [c["name"] for c in cookies_mod.parse(blob)] == ["good", "bad", "also_good"]


def test_exported_cookies_are_valid_json():
    jar = cookies_mod.parse(json.dumps([{"name": "a", "domain": ".x.com",
                                         "expires": "Infinity"}]))
    # json.dumps would happily emit bare `Infinity`, which nothing else can read.
    json.loads(cookies_mod.dumps(jar))


# --- proxy credentials with URL-significant characters ----------------------

@pytest.mark.parametrize("line,user,pw", [
    ("http://user:pa/ss@1.2.3.4:8080", "user", "pa/ss"),
    ("http://user:p@ss:w0rd@1.2.3.4:8080", "user", "p@ss:w0rd"),
    ("1.2.3.4:8080:user:p#ssword", "user", "p#ssword"),
])
def test_proxy_url_survives_special_characters(line, user, pw):
    import urllib.parse as up
    parsed = up.urlsplit(_proxy_url(parse_line(line)))
    assert parsed.hostname == "1.2.3.4" and parsed.port == 8080
    assert up.unquote(parsed.username) == user
    assert up.unquote(parsed.password) == pw


# --- an export that says "no proxy" must not produce one --------------------

@pytest.mark.parametrize("px", [
    {"type": "none", "host": "1.2.3.4", "port": "8080"},
    {"mode": "none", "host": "1.2.3.4", "port": "8080"},
    {"proxy_type": "no_proxy", "host": "1.2.3.4", "port": "8080"},
])
def test_direct_export_yields_no_proxy(px):
    assert _parse_proxy({"proxy": px}) is None


def test_a_real_proxy_still_imports():
    got = _parse_proxy({"proxy": {"mode": "http", "host": "1.2.3.4", "port": "8080",
                                  "username": "u", "password": "p"}})
    assert got is not None and got.server == "http://1.2.3.4:8080"


# --- bulk select de-duplicates by identity, not by value --------------------

def test_select_keeps_distinct_profiles_with_identical_fields():
    fp = generate(os="windows", seed=1)
    a = Profile(name="dup", fingerprint=fp, tags=["t"])
    b = Profile(name="dup", fingerprint=fp, tags=["t"])
    assert a.id != b.id
    got = select([a, b], refs=["dup"], tag="t")
    assert len({p.id for p in got}) == 2, "two real profiles must not collapse into one"


# --- navigator.deviceMemory must be a value Chrome can actually report ------
# The Device Memory spec clamps to [0.25, 8] and rounds to a power of two, so
# reporting a machine's true 16 or 32 GB is an instant tell.

@pytest.mark.parametrize("gb,expected", [
    (2, 2.0), (4, 4.0), (6, 4.0), (8, 8.0), (12, 8.0), (16, 8.0), (32, 8.0),
    (0, 0.25), (-5, 0.25), ("nonsense", 8.0), (None, 8.0),
])
def test_reported_device_memory_is_always_legal(gb, expected):
    from qwerty.devices import REPORTABLE_MEMORY, reported_device_memory
    got = reported_device_memory(gb)
    assert got == expected
    assert got in REPORTABLE_MEMORY


def test_stealth_script_never_reports_an_impossible_memory():
    import json as _json
    import re as _re
    from qwerty.devices import REPORTABLE_MEMORY
    from qwerty.stealth import build_init_script

    for os_key in ("windows", "macos", "linux", "android"):
        for seed in range(1, 25):
            fp = generate(os=os_key, seed=seed)
            script = build_init_script(fp)
            cfg = _json.loads(_re.search(r"JSON.parse\((.*?)\)", script).group(1)
                              if "JSON.parse" in script
                              else _re.search(r"cfg = (\{.*?\});", script, _re.S).group(1))
            assert cfg["deviceMemory"] in REPORTABLE_MEMORY, (
                f"{os_key}/{seed}: navigator.deviceMemory={cfg['deviceMemory']} "
                "is a value no real Chrome reports")


# --- devicePixelRatio must match the handset the user-agent names -----------

def test_device_scale_factor_matches_the_handset():
    from qwerty import devices
    from qwerty.drivers import _device_scale_factor

    seen = {}
    for seed in range(1, 60):
        fp = generate(os="android", seed=seed)
        device = devices.android_device_for_ua(fp.user_agent)
        assert device is not None, "every generated Android UA must name a known handset"
        assert _device_scale_factor(fp) == device["dpr"]
        seen[device["model"]] = device["dpr"]
    assert len(set(seen.values())) > 1, "one DPR for every phone is the bug we fixed"


def test_desktop_profiles_report_dpr_one():
    from qwerty.drivers import _device_scale_factor
    for os_key in ("windows", "macos", "linux"):
        assert _device_scale_factor(generate(os=os_key, seed=1)) == 1.0


def test_android_device_lookup_rejects_a_partial_model_match():
    from qwerty.devices import android_device_for_ua
    assert android_device_for_ua("Mozilla/5.0 (Linux; Android 13; Pixel 7)")["model"] == "Pixel 7"
    assert android_device_for_ua("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") is None
    assert android_device_for_ua("") is None


# --- attaching must never drive a browser that was already running ---------

def test_attach_refuses_an_occupied_port(tmp_path):
    import socket as _socket
    from qwerty import automation

    store = ProfileStore(tmp_path)
    prof = store.save(Profile(name="a", fingerprint=generate(os="windows", seed=1),
                              engine="playwright"))
    srv = _socket.socket()
    srv.bind(("127.0.0.1", 0))
    # Backlog large enough for several probes: each port_in_use() actually
    # connects, and a backlog of 1 would make the second probe fail for reasons
    # that have nothing to do with what we're testing.
    srv.listen(16)
    port = srv.getsockname()[1]
    try:
        assert automation.port_in_use(port) is True
        with pytest.raises(RuntimeError, match="already in use"):
            automation.attach(prof, store, port=port)
    finally:
        srv.close()


def test_port_in_use_is_false_for_a_free_port():
    import socket as _socket
    from qwerty.automation import port_in_use
    srv = _socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    assert port_in_use(port) is False


# --- dashboard profiles get a distinct font subset, not the whole pool ------

def test_dashboard_profiles_do_not_share_one_maximal_font_list():
    from qwerty import devices
    from qwerty.server import to_engine_profile

    base = {"os": "Windows", "screen": "1920x1080", "cores": 8, "memory": 16,
            "locale": "en-US", "timezone": "America/New_York",
            "webglRenderer": "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11)"}
    pool = devices.FONTS["windows"]
    ps = [to_engine_profile(dict(base, id="p%d" % i, name="P%d" % i, seed=i))
          for i in range(1, 8)]

    lists = {tuple(p.fingerprint.fonts) for p in ps}
    assert len(lists) > 1, "every profile sharing one font list is the bug"
    assert not all(tuple(pool) == fonts for fonts in lists)
    for p in ps:
        assert set(p.fingerprint.fonts) <= set(pool)
        assert len(p.fingerprint.fonts) >= 6


def test_dashboard_font_list_is_stable_across_rebuilds():
    from qwerty.server import to_engine_profile
    d = {"id": "p1", "name": "P1", "seed": 4242, "os": "Windows",
         "screen": "1920x1080", "cores": 8, "memory": 16, "locale": "en-US",
         "timezone": "America/New_York",
         "webglRenderer": "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11)"}
    assert to_engine_profile(d).fingerprint.fonts == to_engine_profile(d).fingerprint.fonts


def test_real_font_mode_presents_the_whole_pool():
    from qwerty import devices
    from qwerty.server import profile_fonts
    assert profile_fonts("windows", 1, "Real") == devices.FONTS["windows"]
    assert profile_fonts("windows", 1, "Masked") != devices.FONTS["windows"]


def test_seedless_profiles_still_get_distinct_fonts():
    """An older profile stored with seed 0 must not share one list with all of them."""
    from qwerty.server import to_engine_profile
    base = {"os": "Windows", "screen": "1920x1080", "cores": 8, "memory": 16,
            "locale": "en-US", "timezone": "America/New_York",
            "webglRenderer": "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11)"}
    ps = [to_engine_profile(dict(base, id="s%d" % i, name="S%d" % i)) for i in range(6)]
    assert len({tuple(p.fingerprint.fonts) for p in ps}) > 1


# --- an unreachable pool must not become a retry storm ----------------------

def test_warmup_gives_up_when_nothing_is_reachable(monkeypatch):
    """An offline machine used to spin the loop as fast as it could until the
    deadline, hammering every site hundreds of times."""
    import contextlib
    from qwerty import warmup

    attempts = []

    class FakePage:
        def goto(self, url, **kw):
            attempts.append(url)
            raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")   # fails instantly

    class FakeContext:
        pages = [FakePage()]

        def new_page(self):
            return self.pages[0]

    @contextlib.contextmanager
    def fake_session(*a, **k):
        yield FakeContext()

    monkeypatch.setattr(warmup, "session", fake_session)
    monkeypatch.setattr(warmup, "_human_pause", lambda *a, **k: None)

    prof = Profile(name="offline", fingerprint=generate(os="windows", seed=1))
    result = warmup.warm_up(prof, None, minutes=5, headless=True)

    assert result["pages"] == 0
    # Bounded by the give-up rule, not by the five-minute deadline.
    assert len(attempts) <= max(len(warmup.DEFAULT_SITES) * 2, 10)
    assert result["errors"] == len(attempts)


# --- a locked vault must never destroy secrets ------------------------------
# Reading with no/wrong password decrypts secrets to None, so the old
# "refuse to downgrade" guard (`any(self._secret_values(profile))`) never fired
# and that None was written over the ciphertext: an unrelated
# `qwerty edit --notes` permanently lost the proxy password.

def _vaulted_store(tmp_path, password="hunter2"):
    from qwerty.models import Proxy
    store = ProfileStore(tmp_path, password=password)
    prof = Profile(name="v1", fingerprint=generate(os="windows", seed=1),
                   proxy=Proxy(server="http://1.2.3.4:8080", username="u",
                               password="secret123"))
    store.save(prof)
    store.enable_vault(password)
    return store, prof


def _raw_password(store, pid):
    raw = json.loads((store.profiles_dir / f"{pid}.json").read_text(encoding="utf-8"))
    return (raw.get("proxy") or {}).get("password")


def test_locked_edit_preserves_the_encrypted_secret(tmp_path):
    store, prof = _vaulted_store(tmp_path)
    assert str(_raw_password(store, prof.id)).startswith("enc:v1:")

    locked = ProfileStore(tmp_path)                 # no password at all
    p = locked.list()[0]
    assert p.proxy.password is None, "a locked read yields None, not the ciphertext"
    p.notes = "edited while locked"
    locked.save(p)

    # The ciphertext survived, and the unrelated edit still landed.
    assert str(_raw_password(store, prof.id)).startswith("enc:v1:")
    unlocked = ProfileStore(tmp_path, password="hunter2").list()[0]
    assert unlocked.proxy.password == "secret123"
    assert unlocked.notes == "edited while locked"


def test_wrong_password_also_preserves_the_secret(tmp_path):
    store, prof = _vaulted_store(tmp_path)
    wrong = ProfileStore(tmp_path, password="not-it")
    p = wrong.list()[0]
    p.tags = ["touched"]
    wrong.save(p)
    assert ProfileStore(tmp_path, password="hunter2").list()[0].proxy.password == "secret123"


def test_setting_a_new_secret_while_locked_is_refused(tmp_path):
    from qwerty import crypto
    store, prof = _vaulted_store(tmp_path)
    locked = ProfileStore(tmp_path)
    p = locked.list()[0]
    p.proxy.password = "brand-new"                  # a real value, unencryptable
    with pytest.raises(crypto.VaultLocked):
        locked.save(p)
    # And the original is untouched.
    assert ProfileStore(tmp_path, password="hunter2").list()[0].proxy.password == "secret123"


def test_unlocked_saves_still_round_trip(tmp_path):
    """The guard must not get in the way of the normal path."""
    store, prof = _vaulted_store(tmp_path)
    p = store.list()[0]
    p.proxy.password = "rotated"
    store.save(p)
    assert ProfileStore(tmp_path, password="hunter2").list()[0].proxy.password == "rotated"


# --- regen must not silently change the operating system --------------------

def test_regen_keeps_the_os_and_locale_by_default(tmp_path):
    """`apply --regen` and duplicate-as-template both preserve the OS; the CLI's
    `regen` randomised it, which would move a logged-in profile to another OS.

    Driven through main() so it exercises the real argparse path, and repeated
    because the old bug picked a random OS — a single run could pass by luck.
    """
    from qwerty.cli import main
    store = ProfileStore(tmp_path)
    store.save(Profile(name="w1", fingerprint=generate(os="windows", locale="en-GB")))
    args = ["--data-dir", str(tmp_path), "regen", "w1"]

    for _ in range(15):
        assert main(args) == 0
        fp = ProfileStore(tmp_path).list()[0].fingerprint
        assert fp.os == "windows", "regen must not move the profile to another OS"
        assert fp.locale == "en-GB"

    # An explicit override still works.
    assert main(["--data-dir", str(tmp_path), "regen", "w1", "--os", "linux"]) == 0
    assert ProfileStore(tmp_path).list()[0].fingerprint.os == "linux"


# --- the stealth script must reach the page that already exists -------------
# add_init_script only applies from the next document onward, so the about:blank
# page a persistent context opens never got it — and that is precisely the page
# `qwerty attach` hands to an automation script (contexts[0].pages[0]). Anyone
# checking their fingerprint before navigating saw the real machine.

class _FakePage:
    def __init__(self, fail=False):
        self.evaluated = []
        self._fail = fail

    def evaluate(self, script, *a):
        if self._fail:
            raise RuntimeError("navigating")
        self.evaluated.append(script)


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages


def test_open_pages_receive_the_stealth_script():
    from qwerty.drivers import _apply_to_open_pages
    pages = [_FakePage(), _FakePage()]
    _apply_to_open_pages(_FakeContext(pages), "STEALTH")
    assert [p.evaluated for p in pages] == [["STEALTH"], ["STEALTH"]]


def test_a_page_that_throws_does_not_abort_the_rest():
    from qwerty.drivers import _apply_to_open_pages
    good, bad = _FakePage(), _FakePage(fail=True)
    _apply_to_open_pages(_FakeContext([bad, good]), "STEALTH")
    assert good.evaluated == ["STEALTH"], "one mid-navigation page must not block others"


def test_no_open_pages_is_fine():
    from qwerty.drivers import _apply_to_open_pages
    _apply_to_open_pages(_FakeContext([]), "STEALTH")
    _apply_to_open_pages(_FakeContext(None), "STEALTH")


def test_the_script_actually_patches_the_spoofed_values():
    """Guard the contents too: the script must carry this profile's numbers."""
    from qwerty.stealth import build_init_script
    fp = generate(os="windows", seed=11)
    script = build_init_script(fp)
    assert str(fp.hardware_concurrency) in script
    assert "hardwareConcurrency" in script and "deviceMemory" in script


# --- deleting a profile must not leave an unrunnable schedule ---------------

def test_deleting_a_profile_drops_its_schedules(tmp_path):
    store = ScheduleStore(tmp_path)
    keep = store.add(profile_id="keep-me", every_hours=1, now=time.time())["id"]
    for _ in range(3):
        store.add(profile_id="doomed", every_hours=1, now=time.time())

    assert store.delete_for_profile("doomed") == 3
    assert [s["id"] for s in store.list()] == [keep]
    # Idempotent, and a profile with none is not an error.
    assert store.delete_for_profile("doomed") == 0
    assert store.delete_for_profile("never-existed") == 0


# --- cookie import must report what the browser actually kept ---------------

def test_cookie_write_counts_only_what_persisted():
    """Chromium silently drops an already-expired cookie; "Imported 3" when only
    2 survived left the user unable to reconcile it with `cookies list`."""
    from qwerty import cookies as ck

    submitted = [
        {"name": "a", "domain": ".x.com", "value": "1"},
        {"name": "b", "domain": ".x.com", "value": "2"},
        {"name": "gone", "domain": ".x.com", "value": "3"},
    ]

    class Ctx:
        def clear_cookies(self): pass
        def add_cookies(self, c): pass
        def cookies(self):       # the browser kept only two of them
            return [{"name": "a", "domain": ".x.com"}, {"name": "b", "domain": ".x.com"}]

    import contextlib

    @contextlib.contextmanager
    def fake_session(*a, **k):
        yield Ctx()

    import qwerty.drivers as drivers_mod
    real = drivers_mod.session
    drivers_mod.session = fake_session
    try:
        assert ck.write(None, None, submitted) == 2
    finally:
        drivers_mod.session = real
