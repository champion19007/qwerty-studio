"""
Profile storage.

Profiles live as individual JSON files under a data directory (default
``~/.qwerty/profiles``). One file per profile keeps things transparent,
diff-friendly and trivial to back up or sync. Browser user-data (cookies,
localStorage) is kept in a sibling ``user-data/<id>`` directory that the
launcher points the browser at, so sessions persist between runs.
"""

from __future__ import annotations

import json
import os
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from . import crypto
from .models import Profile


class UnsafeArchive(ValueError):
    """Raised when a backup archive contains a path that escapes its target dir."""


def _safe_member_path(base: Path, member: str) -> Path:
    """Resolve ``member`` inside ``base``, refusing anything that escapes it.

    A zip stores plain strings, and nothing stops one from reading
    ``../../../.bashrc`` or ``C:/Windows/system32/x``. Since backups are designed
    to be carried between machines, we can't assume the archive is friendly:
    resolve the joined path and confirm it is still under ``base``.
    """
    if member.startswith(("/", "\\")) or (len(member) > 1 and member[1] == ":"):
        raise UnsafeArchive(f"absolute path in archive: {member!r}")
    target = (base / member).resolve()
    root = base.resolve()
    if target != root and root not in target.parents:
        raise UnsafeArchive(f"path escapes the profile directory: {member!r}")
    return target


class ProfileStore:
    def __init__(self, root: Optional[str | Path] = None,
                 password: Optional[str] = None):
        self.root = Path(root or (Path.home() / ".qwerty")).expanduser()
        self.profiles_dir = self.root / "profiles"
        self.userdata_dir = self.root / "user-data"
        self.config_path = self.root / "config.json"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.userdata_dir.mkdir(parents=True, exist_ok=True)
        # The master password comes from the caller or the environment, so a
        # launched subprocess inherits it without it ever hitting disk.
        self._password = password or os.environ.get("QWERTY_PASSWORD") or None

    # ---- config (small key/value settings) -------------------------------
    # CloakBrowser is the top-priority default: it's the strongest engine.
    DEFAULT_ENGINE = "cloak"

    def get_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save_config(self, cfg: dict) -> dict:
        self.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg

    def get_default_engine(self) -> str:
        """The engine used for new profiles when none is given (persisted)."""
        return self.get_config().get("default_engine") or self.DEFAULT_ENGINE

    def set_default_engine(self, name: str) -> str:
        cfg = self.get_config()
        cfg["default_engine"] = name
        self.save_config(cfg)
        return name

    # ---- vault (encrypt-at-rest for secrets) -----------------------------
    # The fields worth encrypting: anything that grants access if leaked. Cookies
    # live in Chromium's own encrypted store, so the one in our plaintext JSON is
    # the proxy password.
    SECRET_PATHS = (("proxy", "password"),)

    def vault(self) -> Optional[dict]:
        """The vault descriptor ({salt, verifier}) if a password was ever set."""
        return self.get_config().get("vault")

    def vault_enabled(self) -> bool:
        return self.vault() is not None

    def unlocked(self) -> bool:
        """True when secrets can actually be read/written (right password set)."""
        v = self.vault()
        if not v:
            return True                      # nothing to unlock
        return bool(self._password) and crypto.check_password(
            self._password, v["salt"], v["verifier"])

    def enable_vault(self, password: str) -> int:
        """Turn on the vault and encrypt every existing secret. Returns the count."""
        crypto._require()
        if self.vault_enabled():
            raise RuntimeError("A vault is already set up for this data directory.")
        salt = crypto.new_salt()
        cfg = self.get_config()
        cfg["vault"] = {"salt": salt, "verifier": crypto.make_verifier(password, salt)}
        self.save_config(cfg)
        self._password = password
        # Re-save every profile so its secrets get written back encrypted.
        n = 0
        for prof in self.list():
            if any(self._secret_values(prof)):
                self.save(prof)
                n += 1
        return n

    def _secret_values(self, profile: Profile) -> list:
        vals = []
        d = profile.to_dict()
        for a, b in self.SECRET_PATHS:
            sec = (d.get(a) or {}).get(b) if isinstance(d.get(a), dict) else None
            vals.append(sec)
        return vals

    def _apply_secrets(self, data: dict, mode: str) -> dict:
        """Encrypt (mode='enc') or decrypt (mode='dec') the secret fields in a
        profile dict, in place. A no-op when there's no vault."""
        v = self.vault()
        if not v:
            return data
        pw = self._password
        for a, b in self.SECRET_PATHS:
            node = data.get(a)
            if not isinstance(node, dict) or not node.get(b):
                continue
            val = node[b]
            if mode == "enc":
                if pw and self.unlocked() and not crypto.is_encrypted(val):
                    node[b] = crypto.encrypt(pw, v["salt"], val)
            else:  # dec
                if crypto.is_encrypted(val):
                    node[b] = crypto.decrypt(pw, v["salt"], val) if (pw and self.unlocked()) else None
        return data

    # ---- paths -----------------------------------------------------------
    def _path(self, profile_id: str) -> Path:
        return self.profiles_dir / f"{profile_id}.json"

    def user_data_path(self, profile_id: str) -> Path:
        p = self.userdata_dir / profile_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---- CRUD ------------------------------------------------------------
    def _stored_secrets(self, profile_id: str) -> dict:
        """The still-encrypted secret values currently on disk, by path.

        Read raw — no decryption — so this works while the vault is locked.
        """
        path = self._path(profile_id)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        out = {}
        for a, b in self.SECRET_PATHS:
            node = raw.get(a)
            if isinstance(node, dict) and crypto.is_encrypted(node.get(b)):
                out[(a, b)] = node[b]
        return out

    def save(self, profile: Profile) -> Profile:
        profile.updated_at = time.time()
        data = self._apply_secrets(profile.to_dict(), "enc")

        # Saving while the vault is locked used to *destroy* secrets. Reading a
        # profile with no (or the wrong) password decrypts its secrets to None,
        # so `any(self._secret_values(profile))` was False, the old guard never
        # fired, and that None was written straight over the ciphertext — an
        # unrelated `qwerty edit --notes` permanently lost the proxy password.
        #
        # Two distinct cases, handled separately:
        #   * the in-memory secret is None — we simply never decrypted it, so
        #     carry the on-disk ciphertext across untouched. Editing notes and
        #     tags without the master password stays possible, and is safe.
        #   * the in-memory secret is a real value the caller just set — we
        #     cannot encrypt it while locked, and writing it in the clear would
        #     downgrade the vault, so refuse. (This was the original intent.)
        if self.vault_enabled() and not self.unlocked():
            stored = self._stored_secrets(profile.id)
            for a, b in self.SECRET_PATHS:
                node = data.get(a)
                if not isinstance(node, dict):
                    continue
                value = node.get(b)
                if value is None or crypto.is_encrypted(value):
                    if (a, b) in stored:
                        node[b] = stored[(a, b)]        # keep what is on disk
                elif value:
                    raise crypto.VaultLocked(
                        "the vault is locked — unlock with the master password before "
                        f"setting a new {a} {b}")

        self._path(profile.id).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return profile

    def get(self, profile_id: str) -> Optional[Profile]:
        path = self._path(profile_id)
        if not path.exists():
            return None
        data = self._apply_secrets(json.loads(path.read_text(encoding="utf-8")), "dec")
        return Profile.from_dict(data)

    def find_by_name(self, name: str) -> Optional[Profile]:
        for p in self.list():
            if p.name == name:
                return p
        return None

    def resolve(self, ref: str) -> Optional[Profile]:
        """Look up a profile by id first, then by name."""
        return self.get(ref) or self.find_by_name(ref)

    # A profile file can be unreadable in more ways than bad JSON: a file written
    # by a different version can be missing a field that is now required, which
    # surfaces as TypeError from the dataclass constructor, or hold the wrong
    # type for one, which surfaces as ValueError. Catching only JSONDecodeError
    # and KeyError meant a single such file took down the entire listing — and
    # with it `qwerty list`, the dashboard grid, Health and collisions.
    # AttributeError covers a field holding the wrong *shape* entirely (a string
    # where a dict belongs), which from_dict hits as `"...".items()`.
    UNREADABLE = (json.JSONDecodeError, KeyError, TypeError, ValueError,
                  AttributeError, OSError)

    def list(self) -> list[Profile]:
        """Every readable profile, oldest first. Unreadable files are skipped.

        Use :meth:`list_with_errors` when you need to know *which* files were
        skipped and why — silently dropping a profile is right for a grid, but
        wrong for a diagnostic."""
        profiles, _ = self.list_with_errors()
        return profiles

    def list_with_errors(self) -> tuple[list[Profile], list[dict]]:
        """Like :meth:`list`, plus one ``{"file", "error"}`` entry per skipped file."""
        out: list[Profile] = []
        skipped: list[dict] = []
        for f in sorted(self.profiles_dir.glob("*.json")):
            try:
                data = self._apply_secrets(json.loads(f.read_text(encoding="utf-8")), "dec")
                out.append(Profile.from_dict(data))
            except crypto.VaultLocked:
                raise                      # a locked vault is the caller's problem
            except self.UNREADABLE as e:
                skipped.append({"file": f.name, "error": f"{type(e).__name__}: {e}"})
        out.sort(key=lambda p: p.created_at)
        return out, skipped

    def delete(self, profile_id: str) -> bool:
        path = self._path(profile_id)
        if not path.exists():
            return False
        path.unlink()
        # best-effort cleanup of user-data
        ud = self.userdata_dir / profile_id
        if ud.exists():
            import shutil
            shutil.rmtree(ud, ignore_errors=True)
        return True

    # ---- import / export -------------------------------------------------
    def export(self, profile_id: str, dest: str | Path) -> Optional[Path]:
        prof = self.get(profile_id)
        if not prof:
            return None
        dest = Path(dest)
        dest.write_text(json.dumps(prof.to_dict(), indent=2), encoding="utf-8")
        return dest

    def import_file(self, src: str | Path) -> Profile:
        data = json.loads(Path(src).read_text(encoding="utf-8"))
        prof = Profile.from_dict(data)
        return self.save(prof)

    # ---- backup / restore ------------------------------------------------
    # ``export``/``import_file`` move only the profile *config* (a JSON file).
    # A backup is the whole identity: the config **and** its browser session
    # (cookies, localStorage — everything under user-data), zipped into one
    # portable file you can archive or carry to another machine.
    def backup(self, profile_id: str, dest: str | Path) -> Optional[Path]:
        """Zip a profile and its entire browser session into one file.

        The profile JSON inside the archive holds any proxy password in
        *plaintext* (secrets are decrypted on read), so treat a backup file as
        sensitive — it grants everything the profile does. Returns the path, or
        ``None`` if no such profile exists."""
        prof = self.get(profile_id)
        if not prof:
            return None
        dest = Path(dest)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("profile.json", json.dumps(prof.to_dict(), indent=2))
            ud = self.userdata_dir / profile_id
            if ud.exists():
                for f in ud.rglob("*"):
                    if f.is_file():
                        z.write(f, arcname=str(Path("user-data") / f.relative_to(ud)))
        return dest

    def restore(self, src: str | Path, new_id: bool = False) -> Profile:
        """Recreate a profile and its session from a :meth:`backup` archive.

        By default the profile keeps its original id, overwriting any profile
        already under that id (a true restore). Pass ``new_id=True`` to bring it
        in as a fresh copy instead — useful for cloning a warmed-up session
        onto a second machine without the two fighting over one id.

        Backups are meant to travel between machines, so the archive is treated
        as untrusted input: any entry whose path escapes the profile's own
        user-data directory aborts the restore (see :exc:`UnsafeArchive`)."""
        src = Path(src)
        with zipfile.ZipFile(src, "r") as z:
            data = json.loads(z.read("profile.json").decode("utf-8"))
            prof = Profile.from_dict(data)
            if new_id:
                prof.id = uuid.uuid4().hex[:12]
            ud = self.user_data_path(prof.id)
            # Resolve every target *before* writing anything, so a hostile entry
            # aborts the whole restore instead of leaving files half-written.
            planned = []
            for name in z.namelist():
                if not name.startswith("user-data/") or name.endswith("/"):
                    continue
                planned.append((_safe_member_path(ud, name[len("user-data/"):]), name))
            self.save(prof)
            for target, name in planned:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
        return prof
