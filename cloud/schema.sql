-- QWERTY team sync. Two tables, no migrations framework.
--
-- Secrets never arrive here in the clear: the client encrypts proxy passwords
-- with its own vault (Fernet + PBKDF2, see engine/qwerty/crypto.py) before
-- pushing, so `json` holds `enc:v1:` ciphertext the server cannot read. The
-- master password is shared between teammates out of band and never uploaded.

CREATE TABLE IF NOT EXISTS members (
  token_sha256 TEXT PRIMARY KEY,   -- SHA-256 of the bearer token; the token itself is never stored
  name         TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  revoked_at   INTEGER                -- NULL = active
);

CREATE TABLE IF NOT EXISTS profiles (
  id         TEXT PRIMARY KEY,     -- the dashboard profile id
  json       TEXT NOT NULL,        -- the dashboard profile dict, verbatim
  updated_at REAL NOT NULL,        -- the profile's own updated_at, in unix SECONDS; drives last-write-wins
  pushed_by  TEXT NOT NULL,
  pushed_at  INTEGER NOT NULL,     -- server clock, drives `pull --since`
  deleted    INTEGER NOT NULL DEFAULT 0   -- tombstone, so a delete propagates
);

-- `pull --since` is the only hot query.
CREATE INDEX IF NOT EXISTS profiles_pushed_at ON profiles (pushed_at);
