"""Tests for the dashboard<->engine conversion in server.py.

These don't need FastAPI installed — to_engine_profile / dashboard_coherence
live at module level and only touch the engine core.
"""

from qwerty import validate
from qwerty.server import to_engine_profile, dashboard_coherence


BASE = {
    "id": "abc123",
    "name": "Test",
    "os": "Windows",
    "screen": "1920x1080",
    "cores": 8,
    "memory": 16,
    "webglRenderer": "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11)",
    "locale": "en-US",
    "timezone": "America/New_York",
    "browserVersion": "128.0.0.0",
    "userAgent": "Mozilla/5.0 test",
}


def test_converts_os_and_screen():
    fp = to_engine_profile(BASE).fingerprint
    assert fp.os == "windows"
    assert (fp.screen_width, fp.screen_height) == (1920, 1080)
    assert fp.viewport_height < fp.screen_height


def test_maps_gpu_to_real_engine_string():
    fp = to_engine_profile(BASE).fingerprint
    assert "RTX 3060" in fp.webgl_renderer
    assert fp.webgl_vendor.startswith("Google Inc.")


def test_converted_profile_is_coherent():
    # A well-formed dashboard profile must produce a launchable, valid fingerprint.
    assert validate(to_engine_profile(BASE).fingerprint) == []
    assert dashboard_coherence(BASE) == []


def test_proxy_is_converted():
    d = dict(BASE, proxy={"type": "SOCKS5", "host": "h.proxy.io", "port": "1080",
                          "user": "u", "pass": "p", "country": "US"})
    prof = to_engine_profile(d)
    assert prof.proxy is not None
    assert prof.proxy.server == "socks5://h.proxy.io:1080"
    assert prof.proxy.username == "u"


def test_validate_tolerates_missing_id():
    d = {k: v for k, v in BASE.items() if k != "id"}
    # should not raise even without an id (used by the /validate endpoint)
    assert isinstance(dashboard_coherence(d), list)


# --- CORS policy ------------------------------------------------------------
# The API binds to localhost, but that alone doesn't stop a page you have open
# from calling it cross-origin. These lock in the allow-list that replaced the
# old `allow_origins=["*"]`.

import importlib.util

import pytest

from qwerty.server import DASHBOARD_PORTS, create_app, default_origins


def test_default_origins_are_localhost_dashboard_only(monkeypatch):
    monkeypatch.delenv("QWERTY_ALLOWED_ORIGINS", raising=False)
    origins = default_origins()
    assert "*" not in origins
    assert origins, "there must be a concrete allow-list, never an empty one"
    for o in origins:
        assert o.startswith(("http://localhost:", "http://127.0.0.1:"))
    # Both hosts, for every dashboard port we support.
    for port in DASHBOARD_PORTS:
        assert f"http://localhost:{port}" in origins
        assert f"http://127.0.0.1:{port}" in origins


def test_env_var_overrides_the_allow_list(monkeypatch):
    monkeypatch.setenv("QWERTY_ALLOWED_ORIGINS", "https://a.example, https://b.example")
    assert default_origins() == ["https://a.example", "https://b.example"]


def test_blank_env_var_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("QWERTY_ALLOWED_ORIGINS", "   ")
    assert "http://localhost:5173" in default_origins()


@pytest.mark.skipif(importlib.util.find_spec("fastapi") is None,
                    reason="needs the [api] extra")
def test_app_does_not_wildcard_origins(tmp_path, monkeypatch):
    monkeypatch.delenv("QWERTY_ALLOWED_ORIGINS", raising=False)
    app = create_app(str(tmp_path), start_scheduler=False)
    cors = [m for m in app.user_middleware if "CORS" in str(m.cls)]
    assert cors, "CORS middleware should be installed"
    configured = cors[0].kwargs["allow_origins"]
    assert "*" not in configured
    assert "http://localhost:5173" in configured


@pytest.mark.skipif(importlib.util.find_spec("fastapi") is None,
                    reason="needs the [api] extra")
def test_explicit_origins_win_over_defaults(tmp_path):
    app = create_app(str(tmp_path), start_scheduler=False,
                     allowed_origins=["https://studio.example"])
    cors = [m for m in app.user_middleware if "CORS" in str(m.cls)]
    assert cors[0].kwargs["allow_origins"] == ["https://studio.example"]
