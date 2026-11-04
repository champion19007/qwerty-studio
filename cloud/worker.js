/**
 * QWERTY team sync — a Cloudflare Worker over one D1 database.
 *
 * Four routes, bearer-token auth, last-write-wins on each profile's own
 * updated_at. It stores profile *config* only; browser sessions (cookies,
 * localStorage) are deliberately not synced — they are hundreds of megabytes
 * and uploading a live cookie jar is the one thing a profile manager should
 * never do. `qwerty backup` still moves a session between machines by hand.
 *
 *   GET  /whoami            who this token belongs to
 *   GET  /pull?since=<ms>   profiles pushed since a server timestamp
 *   POST /push              {profiles:[...], deleted:[id,...]}
 *   POST /members           mint a member token (needs ADMIN_TOKEN)
 *   DELETE /members/:name   revoke every token for a member
 */

const JSON_HEADERS = { "content-type": "application/json" };
const MAX_BODY = 8 * 1024 * 1024;   // a batch of a few thousand profiles

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Resolve a bearer token to a member, or null.
 *
 * The lookup is by hash against an indexed primary key, so no token or digest
 * is ever compared in JS — there is nothing here to time.
 */
async function authenticate(request, env) {
  const header = request.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return null;
  return env.DB.prepare(
    "SELECT name FROM members WHERE token_sha256 = ? AND revoked_at IS NULL"
  ).bind(await sha256Hex(token)).first();
}

/** Admin routes are gated by a secret, not by a role column. */
function isAdmin(request, env) {
  const header = request.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  // ponytail: single shared admin secret, add a role column if you need
  // more than one person minting tokens.
  return Boolean(env.ADMIN_TOKEN) && token === env.ADMIN_TOKEN;
}

async function readJson(request) {
  const length = Number(request.headers.get("content-length") || 0);
  if (length > MAX_BODY) throw new Error("body too large");
  const body = await request.json();
  if (!body || typeof body !== "object") throw new Error("expected a JSON object");
  return body;
}

async function push(request, env, member) {
  const body = await readJson(request);
  const profiles = Array.isArray(body.profiles) ? body.profiles : [];
  const deleted = Array.isArray(body.deleted) ? body.deleted : [];
  const now = Date.now();
  const statements = [];

  for (const profile of profiles) {
    if (!profile || typeof profile !== "object" || !profile.id) continue;
    // Last-write-wins: keep whichever copy has the newer updated_at. Doing it
    // in the WHERE clause makes the whole push one atomic batch, so two
    // teammates pushing at once cannot interleave into a lost update.
    statements.push(
      env.DB.prepare(
        `INSERT INTO profiles (id, json, updated_at, pushed_by, pushed_at, deleted)
         VALUES (?1, ?2, ?3, ?4, ?5, 0)
         ON CONFLICT(id) DO UPDATE SET
           json = excluded.json, updated_at = excluded.updated_at,
           pushed_by = excluded.pushed_by, pushed_at = excluded.pushed_at,
           deleted = 0
         WHERE excluded.updated_at > profiles.updated_at`
      ).bind(profile.id, JSON.stringify(profile),
             Number(profile.updated_at || profile._created || 0), member.name, now)
    );
  }

  for (const id of deleted) {
    if (typeof id !== "string" || !id) continue;
    // A delete always wins over whatever is stored: no updated_at guard here, so
    // a teammate's delete is not silently dropped. Re-creating the id later
    // still works, because the row keeps its own updated_at and a later edit
    // compares greater.
    //
    // updated_at is in SECONDS throughout (it is the profile's own value), so a
    // brand-new tombstone must seed seconds too. Seeding Date.now() put
    // milliseconds in the column, and no real edit could ever compare greater —
    // that id would have stayed deleted forever.
    statements.push(
      env.DB.prepare(
        `INSERT INTO profiles (id, json, updated_at, pushed_by, pushed_at, deleted)
         VALUES (?1, '{}', ?2, ?3, ?4, 1)
         ON CONFLICT(id) DO UPDATE SET
           deleted = 1, pushed_by = excluded.pushed_by, pushed_at = excluded.pushed_at`
      ).bind(id, now / 1000, member.name, now)
    );
  }

  if (statements.length) await env.DB.batch(statements);
  return json({ ok: true, pushed: profiles.length, deleted: deleted.length, at: now });
}

async function pull(url, env) {
  const since = Number(url.searchParams.get("since") || 0);
  const { results } = await env.DB.prepare(
    "SELECT id, json, deleted, pushed_at, pushed_by FROM profiles WHERE pushed_at > ? ORDER BY pushed_at"
  ).bind(Number.isFinite(since) ? since : 0).all();

  const profiles = [];
  const deleted = [];
  for (const row of results || []) {
    if (row.deleted) { deleted.push(row.id); continue; }
    try { profiles.push(JSON.parse(row.json)); } catch { /* skip a corrupt row */ }
  }
  // `now` is the cursor for the next pull; the client stores it verbatim.
  return json({ profiles, deleted, now: Date.now() });
}

async function addMember(request, env) {
  const body = await readJson(request);
  const name = String(body.name || "").trim();
  if (!name) return json({ error: "name is required" }, 400);
  // 32 random bytes, base64url. Shown once — only its hash is stored.
  const raw = crypto.getRandomValues(new Uint8Array(32));
  const token = btoa(String.fromCharCode(...raw))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  await env.DB.prepare(
    "INSERT INTO members (token_sha256, name, created_at) VALUES (?, ?, ?)"
  ).bind(await sha256Hex(token), name, Date.now()).run();
  return json({ name, token, note: "store it now — it is not recoverable" });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (!env.DB) return json({ error: "no D1 binding named DB" }, 500);

    try {
      if (path === "/members" && request.method === "POST") {
        if (!isAdmin(request, env)) return json({ error: "admin token required" }, 403);
        return await addMember(request, env);
      }
      if (path.startsWith("/members/") && request.method === "DELETE") {
        if (!isAdmin(request, env)) return json({ error: "admin token required" }, 403);
        const name = decodeURIComponent(path.slice("/members/".length));
        const { meta } = await env.DB.prepare(
          "UPDATE members SET revoked_at = ? WHERE name = ? AND revoked_at IS NULL"
        ).bind(Date.now(), name).run();
        return json({ revoked: meta.changes });
      }

      const member = await authenticate(request, env);
      if (!member) return json({ error: "invalid or revoked token" }, 401);

      if (path === "/whoami") return json({ name: member.name });
      if (path === "/pull" && request.method === "GET") return await pull(url, env);
      if (path === "/push" && request.method === "POST") return await push(request, env, member);
      return json({ error: `no route for ${request.method} ${path}` }, 404);
    } catch (err) {
      return json({ error: String(err && err.message || err) }, 400);
    }
  },
};
