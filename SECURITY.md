# Security Policy

## Reporting a vulnerability

If you find a security issue, please **do not** open a public issue. Instead,
email the maintainer or use GitHub's private "Report a vulnerability" feature
under the Security tab. Include steps to reproduce and the potential impact.

You can expect an acknowledgement within a few days and an update on the fix
timeline after triage.

## Scope

QWERTY stores profile data locally as JSON under `~/.qwerty`. Treat that
directory as sensitive.

**Encrypting secrets:** proxy passwords can be encrypted at rest with a master
password — run `pip install -e ".[secure]"` then `qwerty vault enable`. Secrets
are stored as Fernet tokens (AES) with the key derived via PBKDF2-HMAC-SHA256;
supply the password at use time through `QWERTY_PASSWORD` or `--password`, so it
never touches disk. The rest of each profile stays readable. There is no password
recovery — losing it means losing the encrypted secrets.

**The local API (`qwerty serve`):** the server binds to `127.0.0.1`, but binding
to localhost is not by itself an access control — a browser will happily send a
cross-origin request to `http://127.0.0.1:8787` from any page you have open. The
API therefore accepts requests only from the dashboard's own origins
(`http://localhost:5173` / `:4173` and the `127.0.0.1` equivalents). Widen it
deliberately if you need to:

```bash
qwerty serve --allow-origin https://studio.internal.example
# or: QWERTY_ALLOWED_ORIGINS=https://studio.internal.example qwerty serve
```

Do **not** set it to `*`. The API has no authentication of its own, so its origin
allow-list is the boundary: anything permitted through it can read profiles
(including decrypted proxy passwords), launch browsers and delete data.

**Backups are untrusted input:** `qwerty restore` treats an archive as hostile
until proven otherwise — entries whose paths escape the profile's user-data
directory abort the restore rather than writing outside it. Note the reverse
direction too: a backup you *create* contains the proxy password in plaintext
(secrets are decrypted on read), so treat the `.zip` itself as a secret.

Not yet covered: the dashboard's own profile store (profiles created through the
web UI are written as plain JSON and do **not** currently go through the vault,
so a proxy password entered there is stored in the clear), cookies (Chromium
keeps those in its own OS-encrypted store), full-profile encryption, and
authentication on the local API. Contributions welcome.
