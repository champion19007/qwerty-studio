"""
Cookie import / export.

Moving an account between machines (or seeding a fresh profile with a session
you already own) is the single most-requested job of a profile manager, so
QWERTY speaks the formats people actually have on disk:

  * **Playwright storage state** — ``{"cookies": [...], "origins": [...]}``
  * **Browser-extension JSON** — the flat list produced by EditThisCookie,
    Cookie-Editor, and friends (``expirationDate``, ``sameSite: "no_restriction"``…)
  * **Netscape ``cookies.txt``** — what curl/wget/yt-dlp read and write

Everything is normalised to Playwright's cookie shape on the way in, and can be
written back out as either JSON or ``cookies.txt``.

Reading and writing the cookies themselves goes through the browser rather than
the profile's SQLite file: Chromium encrypts cookie values at rest (DPAPI on
Windows, Keychain on macOS), so the only portable way in or out is to open the
profile headlessly and use the real cookie store.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from .models import Profile
from .store import ProfileStore

# Extension exports spell sameSite in their own way; Playwright wants these.
_SAME_SITE = {
    "no_restriction": "None", "none": "None",
    "lax": "Lax", "unspecified": "Lax", "": "Lax",
    "strict": "Strict",
}


def _coerce_expiry(value, session: bool = False) -> float:
    """Turn any dialect's expiry into a Playwright expiry (-1 = session cookie).

    Exports in the wild carry expiry as a number, a numeric string, an ISO-8601
    timestamp, or something unusable. A cookie whose expiry we can't read is
    still a perfectly good *session* cookie, so it degrades to -1 rather than
    raising — one odd entry must never abort an import of several hundred.
    Non-finite values (a stray "Infinity") also become -1: they would otherwise
    serialise as bare `Infinity`, which is not valid JSON for anything reading
    the file back.
    """
    if session or value in (None, "", 0, False):
        return -1.0
    try:
        out = float(value)
    except (TypeError, ValueError):
        # Numeric-looking ISO timestamps ("2026-01-01T00:00:00Z") and anything
        # else we can't parse: treat as a session cookie.
        try:
            from datetime import datetime
            text = str(value).strip().replace("Z", "+00:00")
            return float(datetime.fromisoformat(text).timestamp())
        except (TypeError, ValueError):
            return -1.0
    if not math.isfinite(out):
        return -1.0
    return out


def normalize(raw: dict) -> Optional[dict]:
    """Map one cookie from any supported dialect to Playwright's shape.

    Returns ``None`` for entries too incomplete to be usable (no name, or no
    domain to attach them to).
    """
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    domain = raw.get("domain") or raw.get("host")
    if not name or not domain:
        return None

    # "expirationDate" (extensions) and "expires" (Playwright) mean the same
    # thing; a session cookie is -1.
    expires = _coerce_expiry(raw.get("expires", raw.get("expirationDate")),
                             session=bool(raw.get("session")))

    cookie = {
        "name": str(name),
        "value": str(raw.get("value", "")),
        "domain": str(domain),
        "path": str(raw.get("path") or "/"),
        "expires": expires,
        "httpOnly": bool(raw.get("httpOnly", False)),
        "secure": bool(raw.get("secure", False)),
        "sameSite": _SAME_SITE.get(str(raw.get("sameSite", "")).lower(), "Lax"),
    }
    # Chromium rejects SameSite=None unless the cookie is also Secure.
    if cookie["sameSite"] == "None" and not cookie["secure"]:
        cookie["sameSite"] = "Lax"
    return cookie


def parse_netscape(text: str) -> list[dict]:
    """Parse a Netscape ``cookies.txt`` file (the curl/wget/yt-dlp format)."""
    out = []
    for line in text.splitlines():
        raw = line.strip()
        # "#HttpOnly_" is a real prefix, not a comment.
        http_only = raw.startswith("#HttpOnly_")
        if http_only:
            raw = raw[len("#HttpOnly_"):]
        elif not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 7:
            parts = raw.split()
        if len(parts) < 7:
            continue
        domain, _flag, path, secure, expiry, name, value = parts[:7]
        c = normalize({
            "name": name, "value": value, "domain": domain, "path": path,
            "expires": float(expiry) if expiry.replace(".", "", 1).isdigit() else -1,
            "secure": secure.upper() == "TRUE", "httpOnly": http_only,
        })
        if c:
            out.append(c)
    return out


def parse(text: str) -> list[dict]:
    """Parse cookies from any supported format and return Playwright cookies."""
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_netscape(text)

    if isinstance(data, dict):
        data = data.get("cookies", [data])  # storage state, or a lone cookie
    if not isinstance(data, list):
        return []
    return [c for c in (normalize(x) for x in data) if c]


def to_netscape(cookies: list[dict]) -> str:
    """Serialise cookies as a Netscape ``cookies.txt`` file."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# Exported by QWERTY — https://github.com/champion19007/qwerty-studio",
        "",
    ]
    for c in cookies:
        domain = c["domain"]
        # A leading dot marks a domain cookie (valid for subdomains too).
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        prefix = "#HttpOnly_" if c.get("httpOnly") else ""
        lines.append("\t".join([
            prefix + domain,
            include_sub,
            c.get("path", "/"),
            "TRUE" if c.get("secure") else "FALSE",
            str(int(c.get("expires", -1) or -1)),
            c["name"],
            c.get("value", ""),
        ]))
    return "\n".join(lines) + "\n"


def dumps(cookies: list[dict], fmt: str = "json") -> str:
    """Render cookies as ``json`` (Playwright storage state) or ``netscape``."""
    if fmt == "netscape":
        return to_netscape(cookies)
    return json.dumps({"cookies": cookies, "origins": []}, indent=2)


# --------------------------------------------------------------------------
# Reading / writing the profile's real cookie store.
# --------------------------------------------------------------------------
def read(profile: Profile, store: ProfileStore, engine: Optional[str] = None) -> list[dict]:
    """Read every cookie in the profile's session."""
    from .drivers import session
    with session(profile, store, engine) as context:
        return [c for c in (normalize(dict(c)) for c in context.cookies()) if c]


def write(profile: Profile, store: ProfileStore, cookies: list[dict],
          clear: bool = False, engine: Optional[str] = None) -> int:
    """Add ``cookies`` to the profile's session; returns how many *persisted*.

    With ``clear=True`` the existing jar is emptied first, so the profile ends up
    with exactly the cookies you supplied. The return value counts the cookies
    the browser actually kept, which can be fewer than were supplied — Chromium
    discards an already-expired cookie without complaint.
    """
    if not cookies:
        return 0
    from .drivers import session
    with session(profile, store, engine) as context:
        if clear:
            context.clear_cookies()
        context.add_cookies(cookies)
        # Report what actually landed, not what we submitted. Chromium silently
        # drops cookies it won't keep — an already-expired expiry above all,
        # which is common in an exported session file that has sat around. The
        # old count made "Imported 12" mean "offered 12", and a user whose
        # login didn't come back had no way to tell.
        try:
            names = {(c.get("name"), c.get("domain")) for c in context.cookies()}
        except Exception:
            return len(cookies)
        return sum(1 for c in cookies if (c.get("name"), c.get("domain")) in names)


def read_file(path: str | Path) -> list[dict]:
    """Parse a cookie file from disk (format detected from its contents)."""
    return parse(Path(path).read_text(encoding="utf-8"))
