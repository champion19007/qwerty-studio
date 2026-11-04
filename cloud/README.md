# QWERTY team sync

A Cloudflare Worker over one D1 database that shares **profile config** between
machines and teammates. Roughly 150 lines of server; free tier covers a small
team comfortably.

## What syncs, and what deliberately does not

| | |
|---|---|
| ✅ Profile config | fingerprint, proxy host/port, folders, tags, notes, engine, startup URLs |
| ❌ Browser sessions | cookies and `localStorage` are hundreds of MB, and uploading a live cookie jar is the one thing a profile manager must not do. Use `qwerty backup` to move a session deliberately. |
| ❌ Master password | proxy passwords are encrypted *before* they leave, by the vault already in the engine. The server stores opaque `enc:v1:` tokens it cannot read. Share the master password with teammates out of band. |
| ❌ Per-machine state | run status, activity log, cached trust grade and session health stay local. |

`qwerty sync push` **refuses** to upload a profile whose proxy password is not
encrypted. Enable the vault first (`qwerty vault enable`).

## Deploy

```bash
cd cloud
npx wrangler d1 create qwerty-sync          # skip if the id in wrangler.toml is yours
npx wrangler d1 execute qwerty-sync --remote --file=schema.sql
npx wrangler secret put ADMIN_TOKEN         # any long random string; gates /members only
npx wrangler deploy
```

## Add a member

```bash
curl -X POST https://qwerty-sync.<you>.workers.dev/members \
  -H "authorization: Bearer $ADMIN_TOKEN" \
  -H 'content-type: application/json' -d '{"name":"ahsan"}'
# -> {"name":"ahsan","token":"...","note":"store it now — it is not recoverable"}
```

Only the token's SHA-256 is stored, so a copy of the database yields no working
tokens. Revoke with `DELETE /members/ahsan`; it takes effect on the next request.

## Use it

```bash
qwerty sync login https://qwerty-sync.<you>.workers.dev <member-token>
qwerty sync push           # upload this machine's profiles
qwerty sync pull           # fetch and merge; --dry-run to preview
qwerty sync status
```

## A note on Cloudflare's own bot protection

The edge runs a browser integrity check that 403s (error `1010`) any request
whose User-Agent looks automated — including `Python-urllib/3.x`. The client
sets a real User-Agent for exactly this reason. If you write another client,
set one too, or you will get a 403 that never reaches the Worker.

## Conflicts

Last-write-wins per profile, on the profile's own `updated_at` (unix seconds).
A `pull` never overwrites a local profile that is newer than the remote copy, and
a `push` never overwrites a remote copy that is newer. A delete always wins, but
re-creating the same id later works — the row keeps its `updated_at`, so a later
edit compares greater.

<!-- ponytail: last-write-wins loses a concurrent field edit, not data. Anything
     stronger needs per-field history the dashboard has nowhere to display. -->

## Routes

| | |
|---|---|
| `GET /whoami` | who this token belongs to |
| `GET /pull?since=<ms>` | profiles pushed since a server timestamp |
| `POST /push` | `{profiles:[...], deleted:[id,...]}` |
| `POST /members` | mint a token (admin) |
| `DELETE /members/:name` | revoke every token for a member (admin) |

## Testing it locally

```bash
npx wrangler d1 execute qwerty-sync --local --file=schema.sql
npx wrangler dev --local --port 8799 --var ADMIN_TOKEN:test-admin
```

Then point a throwaway data directory at it:

```bash
qwerty --data-dir /tmp/machine-a sync login http://127.0.0.1:8799 <token>
```
