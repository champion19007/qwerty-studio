"""
Team sync client — share profiles across machines and teammates.

The roadmap called this deliberately unbuilt because it needs a backend and a
threat model. The threat model is the short part, so it comes first:

* The server stores profile **config** only. Browser sessions — cookies,
  localStorage, the whole ``user-data`` directory — are never uploaded. They are
  hundreds of megabytes, and a live cookie jar sitting in someone else's
  database is the one thing a profile manager must not do. ``qwerty backup``
  still moves a session between machines deliberately.
* Proxy passwords are encrypted **before** they leave, by the vault that is
  already here (:mod:`qwerty.crypto`). The server receives an opaque
  ``enc:v1:`` token it cannot read. Teammates share the master password out of
  band; it is never uploaded. Pushing a profile that has a proxy password with
  no vault enabled is refused rather than silently sending it in the clear.
* A member is a bearer token. The server stores only its SHA-256, so a database
  copy does not yield working tokens, and revoking a member is one row.

Conflicts are last-write-wins on each profile's own ``updated_at``. For profile
configs edited by a handful of people that is the honest fit: the loser is a
field edit, not data. Anything stronger needs per-field history the dashboard
has nowhere to show.

Uses urllib so the engine core stays dependency-free.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from . import crypto

USER_AGENT = "qwerty-sync/0.1 (+https://github.com/champion19007/qwerty-studio)"

# Fields that must never be uploaded, whatever a caller passes in. `status` and
# `_activity` are this machine's view of a profile, not part of its identity.
LOCAL_ONLY = ("status", "lastActive", "_activity", "_last_active", "_session", "_trust")


class SyncError(RuntimeError):
    """A sync call failed — unreachable server, bad token, or a refused push."""


def _request(cfg: dict, method: str, path: str, body: Optional[dict] = None,
             timeout: float = 30) -> dict:
    url = cfg["url"].rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("authorization", f"Bearer {cfg['token']}")
    # urllib's default UA is "Python-urllib/3.x", which Cloudflare's browser
    # integrity check rejects at the edge with a 403 (error 1010) before the
    # Worker ever runs. Identify as a real client.
    req.add_header("user-agent", USER_AGENT)
    if data:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:                      # noqa: BLE001 - body may be anything
            pass
        raise SyncError(f"{method} {path} failed ({e.code}){': ' + detail if detail else ''}") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise SyncError(f"{method} {path} failed: {e}") from e


# ---- local configuration -------------------------------------------------
# Kept in the data dir's config.json next to `vault` and `default_engine`, so a
# backup of the data directory carries it and nothing new has to be managed.

def get_config(store) -> Optional[dict]:
    """The configured remote, or ``None``. Shape: ``{url, token, cursor}``."""
    cfg = store.get_config().get("sync")
    return cfg if isinstance(cfg, dict) and cfg.get("url") and cfg.get("token") else None

def set_config(store, url: str, token: str) -> dict:
    cfg = store.get_config()
    existing = cfg.get("sync") if isinstance(cfg.get("sync"), dict) else {}
    # Keep the cursor when only the token is rotated, so a re-login does not
    # force a full re-pull.
    cfg["sync"] = {"url": url.rstrip("/"), "token": token,
                   "cursor": existing.get("cursor", 0) if existing.get("url") == url.rstrip("/") else 0}
    store.save_config(cfg)
    return cfg["sync"]

def _save_cursor(store, cursor: int) -> None:
    cfg = store.get_config()
    if isinstance(cfg.get("sync"), dict):
        cfg["sync"]["cursor"] = int(cursor)
        store.save_config(cfg)


# ---- what actually crosses the wire --------------------------------------

def scrub(profile: dict) -> dict:
    """The uploadable form of a dashboard profile."""
    return {k: v for k, v in profile.items() if k not in LOCAL_ONLY}


def check_secrets(profiles: list[dict], store) -> list[str]:
    """Names of profiles whose proxy password would be uploaded in the clear.

    A push is refused when this is non-empty. Returning the names rather than
    raising lets the CLI say *which* profiles to fix.
    """
    offenders = []
    for p in profiles:
        secret = (p.get("proxy") or {}).get("pass") or (p.get("proxy") or {}).get("password")
        if secret and not crypto.is_encrypted(secret):
            offenders.append(p.get("name") or p.get("id") or "?")
    return offenders


def whoami(cfg: dict) -> dict:
    return _request(cfg, "GET", "/whoami")


def push(store, dash, dry_run: bool = False) -> dict:
    """Upload every local profile. Returns a summary dict."""
    cfg = get_config(store)
    if not cfg:
        raise SyncError("no remote configured — run `qwerty sync login <url> <token>`")

    profiles = [scrub(p) for p in dash.list()]
    unsafe = check_secrets(profiles, store)
    if unsafe:
        raise SyncError(
            "these profiles have an unencrypted proxy password: "
            + ", ".join(unsafe[:5]) + ("…" if len(unsafe) > 5 else "")
            + "\nEnable the vault first (`qwerty vault enable`) so secrets are "
              "encrypted before they leave this machine.")
    if dry_run:
        return {"ok": True, "pushed": len(profiles), "deleted": 0, "dry_run": True}
    return _request(cfg, "POST", "/push", {"profiles": profiles, "deleted": []})


def pull(store, dash, dry_run: bool = False) -> dict:
    """Fetch remote changes since the stored cursor and merge them locally.

    Last-write-wins per profile: a remote copy is written only when its
    ``updated_at`` is newer than the local one, so a pull never clobbers an
    edit made here that has not been pushed yet.
    """
    cfg = get_config(store)
    if not cfg:
        raise SyncError("no remote configured — run `qwerty sync login <url> <token>`")

    got = _request(cfg, "GET", f"/pull?since={int(cfg.get('cursor') or 0)}")
    local = {p["id"]: p for p in dash.list()}
    applied, skipped = [], []

    for remote in got.get("profiles", []):
        pid = remote.get("id")
        if not pid:
            continue
        mine = local.get(pid)
        if mine and float(mine.get("updated_at") or 0) >= float(remote.get("updated_at") or 0):
            skipped.append(pid)                # local copy is newer or equal
            continue
        if not dry_run:
            # Keep this machine's own view of the profile; only config syncs.
            merged = dict(remote)
            for field in LOCAL_ONLY:
                if mine and field in mine:
                    merged[field] = mine[field]
            dash.save(merged)
        applied.append(pid)

    removed = []
    for pid in got.get("deleted", []):
        if pid in local:
            if not dry_run:
                dash.delete(pid)
            removed.append(pid)

    if not dry_run:
        _save_cursor(store, got.get("now", 0))
    return {"ok": True, "applied": applied, "skipped": skipped, "deleted": removed,
            "cursor": got.get("now", 0), "dry_run": dry_run}


def status(store, dash) -> dict:
    cfg = get_config(store)
    if not cfg:
        return {"configured": False, "profiles": len(dash.list())}
    out = {"configured": True, "url": cfg["url"], "cursor": cfg.get("cursor") or 0,
           "profiles": len(dash.list())}
    try:
        out["member"] = whoami(cfg).get("name")
    except SyncError as e:
        out["error"] = str(e)
    out["unencrypted_secrets"] = check_secrets([scrub(p) for p in dash.list()], store)
    return out
