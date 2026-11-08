<div align="center">

# QWERTY Studio

### Open-source, self-hosted anti-detect browser & profile manager

Create browser profiles that each look like a real, separate device — a
*coherent* fingerprint, its own proxy, and a persistent session — then manage
and launch them from a clean web console or CLI.

A self-hosted alternative to GoLogin, Multilogin and AdsPower.

![python](https://img.shields.io/badge/python-3.9%2B-blue)
![react](https://img.shields.io/badge/react-18-61DAFB)
![license](https://img.shields.io/badge/license-MIT-green)
![tests](https://img.shields.io/badge/tests-passing-brightgreen)
![status](https://img.shields.io/badge/status-beta-orange)

<br>

![QWERTY Studio dashboard](docs/screenshot-dashboard.png)

</div>

---

## Why QWERTY?

Most fingerprint tools randomise each value on its own — and that's exactly what
gets them caught. Anti-bot systems don't read values in isolation; they
**cross-check** them. A macOS user-agent with an NVIDIA GPU, or a 4-core phone
claiming a 1440p screen, is an instant tell.

QWERTY's core idea is **coherence**. It picks a realistic device archetype
first, then draws *every* value (OS, user-agent, GPU, screen, CPU, RAM, timezone,
language) from that archetype's real-world pool. The result is an identity whose
parts all agree — and a live coherence check that proves it, both in the engine
(`validate()`) and in the dashboard's real-time meter.

That coherence-first design is the thing commercial tools don't surface, and it's
what makes QWERTY distinctive.

## QWERTY vs the commercial tools

|  | **QWERTY** | Multilogin | GoLogin | AdsPower |
|---|:---:|:---:|:---:|:---:|
| **Price** | **Free** | from ~$99/mo | from ~$49/mo | free tier + paid |
| **Open source** | ✅ MIT | ❌ | ❌ | ❌ |
| **Self-hosted — data never leaves your machine** | ✅ | ❌ cloud | ❌ cloud | ❌ cloud |
| **Live coherence meter** (proves the fingerprint agrees with itself) | ✅ | ❌ | ❌ | ❌ |
| **Trust checker** — grades the *real* browser, not the config | ✅ | ❌ | ❌ | ❌ |
| **Patched-binary stealth engine** | ✅ Cloak / Camoufox | ✅ | ⚠️ | ✅ |
| **Proxy pool + leak/DNS/TLS tests** | ✅ | partial | partial | partial |
| **CLI + Python API** | ✅ | ❌ | limited | limited |
| **Cloud team sync** | ✅ *self-hosted* | ✅ cloud | ✅ cloud | ✅ cloud |

<sub>Pricing and feature comparison are approximate and based on each vendor's public plans at the time of writing — check their sites for current details. QWERTY's team sync is a Worker you deploy to your own Cloudflare account ([cloud/](cloud/)) — nothing is hosted for you, and it syncs profile config only, never sessions or decrypted secrets.</sub>

## What's in the box

QWERTY is a monorepo with two parts that work together:

```
qwerty-studio/
├── engine/        Python core — fingerprints, storage, launcher, CLI
├── dashboard/     React web console — the visual profile manager
└── start.bat      Windows one-click launcher (installs + starts both)
```

| | |
|---|---|
| 🧬 **Coherent fingerprints** | OS, UA, GPU, screen, hardware, timezone & language always agree |
| 🛡️ **Live coherence meter** | Real-time consistency score as you edit — nobody else shows this |
| 🌐 **Proxy-aware** | Set a proxy's country and locale/timezone auto-align to it |
| 🎛️ **Rich editor** | Canvas, WebRTC, audio, fonts, geolocation, media devices, DNT |
| 💾 **Persistent sessions** | Cookies & localStorage survive between launches |
| 🍪 **Cookie import/export** | Move a logged-in session in or out — Cookie-Editor JSON, Playwright state, or `cookies.txt` |
| 🔎 **Trust checker** | Grades the *real* browser against the checks a fingerprinter runs |
| ✨ **Auto-adjust** | One click aligns a profile to what its browser actually presents — grade jumps to A |
| 📡 **Proxy & leak test** | Exit IP, country and timezone match + WebRTC leak detection |
| 🌐 **DNS leak check** | Confirms name lookups exit through the proxy, not your real ISP's resolver |
| 🌐 **Proxy pool** | Import, health-check and assign proxies round-robin across profiles |
| 🔐 **TLS/JA3 check** | Reads the handshake fingerprint — the one layer JS injection can't reach |
| ❤️ **Health overview** | One page: coherence, proxy, trust grade and warm-up schedule per profile |
| 🔑 **Encrypted vault** | Proxy passwords encrypted at rest behind a master password |
| 🧩 **Extensions** | Per-profile unpacked extensions, isolated from every other profile |
| ✨ **Warm-up + schedule** | Human-paced browsing (per-vertical presets) so a fresh profile isn't obviously fresh — and a recurring schedule so it never goes cold |
| 🤖 **Automation attach** | Drive a live profile from Selenium, Puppeteer or Playwright over CDP |
| 🔁 **Bulk edit** | One change applied to hundreds of profiles, coherently |
| 📥 **Migrate in** | Import profiles from GoLogin, AdsPower or Multilogin exports |
| 📦 **Bulk create at scale** | Generate thousands of coherent profiles — mixed OS, country, browser, per-profile hardware (desktop; see the mobile note below) |
| 🗂️ **Folders, tags, search** | Organize hundreds of accounts |
| 🖥️ **Real browser** | Launches a real browser, per-profile isolation |
| 🔌 **Pluggable engines** | Swap the stealth backend: CloakBrowser, Camoufox, Patchright, Playwright |
| 🔗 **Startup URLs** | Each profile opens the pages you want, in its own tabs |
| 🖱️ **One-click launcher** | `start.bat` installs everything and starts both halves on Windows |
| 🔄 **Team sync** | Share profile config across machines via a Cloudflare Worker you own — sessions and decrypted secrets never leave |
| ⌨️ **CLI + Python API** | Script it or drive it by hand |

> **Mobile profiles are early.** `ANDROID_DEVICES` currently holds 6 real
> handsets, and a phone's whole fingerprint is drawn from one of them, so any
> sizeable Android batch will contain shared fingerprints — `qwerty collisions`
> will show you exactly which. Desktop draws from roughly 400 archetypes and
> scales fine. Adding handsets is the fix, and a good first contribution.

## Quick start

**Prerequisites:** [Python 3.9+](https://www.python.org/downloads/) and (for the
dashboard) [Node.js 18+](https://nodejs.org/). Check with `python --version` and
`node --version`.

```bash
git clone https://github.com/champion19007/qwerty-studio.git
cd qwerty-studio
```

### Easiest (Windows): one-click launcher

Double-click **`start.bat`** in the project folder. On first run it installs
everything, lets you pick the default browser engine (CloakBrowser first), then
starts the engine API + dashboard and opens the console in your browser. Two
terminal windows stay open while it runs — close them to stop. To re-run setup,
delete `.qwerty_setup_done`.

The engine you pick "wins": it becomes the default for every new profile you
create afterwards, from the batch menu, the CLI, or the dashboard. Change it any
time with `qwerty default-engine cloak`.

Prefer to do it by hand, or on macOS/Linux? Follow the manual steps below —
the two parts are independent, so you can run the engine, the dashboard, or both.

### 1. Engine (backend)

```bash
cd engine
pip install -e ".[launch]"      # omit [launch] to skip Playwright
playwright install chromium     # downloads the browser (needed for `launch`)

qwerty create acct-01 --os windows --locale en-US
qwerty launch acct-01          # opens a Chromium window; close it to exit
```

> **Windows / PowerShell:** keep the quotes around `".[launch]"` exactly as
> shown — without them the shell mis-reads the brackets.
>
> **`qwerty` not recognized?** The install worked but its Scripts folder isn't
> on your PATH. Either reopen your terminal, or run it as a module instead:
> `python -m qwerty create acct-01 --os windows --locale en-US`.

### 2. Dashboard (frontend)

```bash
cd dashboard
npm install
npm run dev                      # then open http://localhost:5173
```

> The dashboard runs on its own with in-memory **sample data**, so you can
> explore it without the engine (the footer shows *Demo mode*).

### 3. Connect them (launch real browsers from the dashboard)

Start the engine's API, then reload the dashboard — its footer flips to
*Engine online* and the launch (▶) button now opens a **real Chromium window**,
with profiles saved to disk.

```bash
cd engine
pip install -e ".[api,launch]"
playwright install chromium
qwerty serve                    # HTTP API on http://localhost:8787
```

Leave `qwerty serve` running and start the dashboard (`npm run dev`) in a second
terminal. That's it — clicking ▶ launches the profile for real.

### 4. Team sync (optional)

Share profiles between your own machines, or with a team. You host it: the
server is a Cloudflare Worker in **your** account, and nothing is hosted for you.
Free for a small team — see [cloud/README.md](cloud/README.md) for the cost model.

**What crosses the wire:** profile config only. Browser sessions (cookies,
`localStorage`) are never uploaded, and proxy passwords are encrypted by your
local vault first, so the server stores ciphertext it cannot read. Enable the
vault before your first push:

```bash
qwerty vault enable
```

**Deploy the server once:**

```bash
cd cloud
npx wrangler d1 create qwerty-sync                            # put the id in wrangler.toml
npx wrangler d1 execute qwerty-sync --remote --file=schema.sql
npx wrangler secret put ADMIN_TOKEN                           # any long random string
npx wrangler deploy
```

**Mint a token per person** (the admin token only does this; it is never used
by the client):

```bash
curl -X POST https://qwerty-sync.<you>.workers.dev/members   -H "authorization: Bearer $ADMIN_TOKEN"   -H 'content-type: application/json' -d '{"name":"ahsan"}'
```

The token is shown once — only its SHA-256 is stored. Revoke with
`DELETE /members/ahsan`, effective on the next request.

**Then on each machine:**

```bash
qwerty sync login https://qwerty-sync.<you>.workers.dev <member-token>
qwerty sync push           # send profiles changed since your last push
qwerty sync pull           # fetch and merge; --dry-run to preview
qwerty sync status         # remote, member, and what is pending
```

Conflicts are last-write-wins on each profile's own `updated_at`: a pull never
overwrites a local profile that is newer, and a push never overwrites a newer
remote one. Teammates share the vault master password out of band — it is not
uploaded, and without it their copy of a synced proxy password stays encrypted.

Full details live in each part's README:
[engine/README.md](engine/README.md) · [dashboard/README.md](dashboard/README.md) ·
[cloud/README.md](cloud/README.md).

## How it works

```
             ┌──────────────┐
   pick OS → │  archetype   │   curated real-world combos (engine/qwerty/devices.py)
             └──────┬───────┘
                    │  every value drawn from this archetype's pool
                    ▼
             ┌──────────────┐        ┌──────────────┐
             │ Fingerprint  │───────▶│  validate()  │   coherence gate
             └──────┬───────┘        └──────────────┘
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  context options          stealth.js init script
  (UA, viewport, locale,   (navigator.platform, WebGL,
   timezone, proxy, CH)     hardwareConcurrency, webdriver, canvas noise)
        └───────────┬────────────┘
                    ▼
          Chromium (persistent context per profile)
```

See [docs/architecture.md](docs/architecture.md) for the full walkthrough,
including how to connect the dashboard to the engine.

## Manager + pluggable engines

QWERTY's job is to be the **manager** — coherent identities, proxies, sessions,
folders, and a dashboard. The actual stealth browser is a **pluggable engine** you
choose per profile:

| Engine | Strength | Notes |
|---|---|---|
| `cloak` ⭐ | Patched Chromium binary | **Recommended.** CloakBrowser — C++-level fingerprint/TLS/CDP patches; aims at Cloudflare/DataDome/reCAPTCHA-v3-grade evasion. |
| `camoufox` ⭐ | Patched Firefox (C++-level) | **Recommended.** Among the strongest open options; brings its own coherent fingerprint. |
| `patchright` | Runtime-patched Playwright | Drop-in; fixes `webdriver`/CDP leaks the stock engine can't. |
| `playwright` | Built-in, always available | Stock Chromium + injected stealth script. Passes basic bot tests (BrowserScan, sannysoft); can't beat TLS/CDP-level detection. |

```bash
qwerty engines                          # see what's installed + which is default
qwerty create acct-01 --engine cloak    # pick a backend per profile
qwerty default-engine cloak             # set the default for new profiles
```

CloakBrowser is the default out of the box. The last engine you choose anywhere
becomes the default for the next profile you create.

Being honest about limits: pure JavaScript injection (the `playwright` engine)
has a ceiling — for Cloudflare / DataDome / reCAPTCHA-v3-grade evasion, pair a
runtime-patched engine with a residential proxy and a warmed-up session. QWERTY
stays the same manager over all of them.

## Roadmap

**Built**

- [x] Coherent fingerprint engine + `validate()`
- [x] Profile storage, import/export, persistent sessions
- [x] Playwright launcher with proxy support
- [x] Full CLI
- [x] Web dashboard: profile grid, fingerprint editor, coherence meter, bulk create, proxies
- [x] HTTP API (`qwerty serve`) connecting the dashboard to the engine — launch real browsers from the UI
- [x] Pluggable launch engines (CloakBrowser, Camoufox, Patchright, Playwright)
- [x] Persisted default engine + one-click Windows launcher (`start.bat`)
- [x] Per-profile startup URLs
- [x] Cookie import/export (CLI, API, dashboard) — Cookie-Editor JSON,
      Playwright storage state, Netscape `cookies.txt`

- [x] Account warm-up — human-paced browsing that ages a fresh profile
- [x] Local automation API — `qwerty attach` opens CDP for Selenium/Puppeteer/Playwright,
      plus a dashboard **Automation** page (one-click attach + copy-paste connect snippets)
- [x] Multi-profile synchronizer — `qwerty apply`, plus "Edit all" in the dashboard
- [x] Proxy tester + WebRTC leak checker (`qwerty proxy test`)
- [x] Fingerprint trust checker (`qwerty trust`) — grades the real browser, not the config
- [x] Extensions manager, plus fonts, media devices, ClientRects & audio noise

- [x] TLS/JA3 handshake checker (`qwerty tls`) — the pre-JS network layer
- [x] Encrypted secrets at rest (`qwerty vault`) — proxy passwords, master-password
- [x] Geolocation aligned to the proxy country + WebRTC IP-handling enforced at launch

- [x] Import from GoLogin / AdsPower / Multilogin (`qwerty import-from`)

- [x] Auto-adjust (`qwerty align`) — align a profile to what its browser really
      shows so a low trust grade jumps to A
- [x] Bulk create at scale (`qwerty bulk-create`, dashboard) — thousands of
      coherent profiles across OS / country / browser, with a paginated grid
- [x] Proxy pool — import a list, health-check it, and assign round-robin across
      profiles (aligning each profile's locale to its proxy country)
- [x] Dashboard-side import (GoLogin / AdsPower / Multilogin) — an Import button
      that maps each export to a coherent profile

- [x] DNS leak checker (`qwerty dns`) — reads which resolvers actually saw the
      lookups and fails if any escaped the proxy's country
- [x] Warm-up presets per vertical (`--preset ads|ecommerce|crypto|social|news`)
- [x] Scheduled warm-up (`qwerty schedule`) — recurring, unattended; the server
      fires due runs from a background thread, or drive it from cron with
      `schedule run-due`
- [x] Profile health overview — one page grading coherence, proxy, cached trust
      and warm-up schedule across every profile, with one-click fix
- [x] Fingerprint collision detector (`qwerty collisions`, Health page) —
      catches profiles that share a fingerprint before a site links the accounts
- [x] Backup & restore (`qwerty backup` / `restore`) — a profile **and its
      session** zipped into one portable file, movable to another machine
- [x] Bulk grid actions (warm up / export the selection) + tag filtering
- [x] Folders manager (dashboard) — create / rename / delete folders with live
      counts; renaming or deleting one moves its profiles instead of dropping them
- [x] Settings page (dashboard) — theme, default launch engine, storage location
      and data summary, backed by `GET`/`PUT /api/config`
- [x] Mobile (Android) profiles — coherent handset fingerprints (real model in
      the UA, matching GPU/screen/RAM) with touch + device-scale emulation at launch
- [x] Session health (`qwerty session`, dashboard) — reads the cookie jar and
      flags expired / soon-to-expire cookies and which logins are still live
- [x] Duplicate as template — clone a profile's settings with a *fresh* coherent
      fingerprint, so the copy is a distinct device, never a fingerprint twin
- [x] Per-profile activity log — launches, warm-ups, trust runs and session
      checks, shown as a timeline in the editor

- [x] Cloud team sync (`qwerty sync`, [cloud/](cloud/)) — a Cloudflare Worker over
      one D1 database that shares profile *config* across machines. Browser
      sessions are deliberately not synced, and proxy passwords are encrypted by
      the local vault before they leave, so the server stores opaque ciphertext.
      Members are bearer tokens stored only as SHA-256; revocation is one row.
      Self-host it yourself — nothing is hosted for you.

**Next**

- [ ] Team *roles* — sync has one admin secret for minting tokens and no
      per-member permissions beyond revocation. Roles need a real permission
      model, not a column.

Want to help? See [CONTRIBUTING.md](CONTRIBUTING.md).

## Legitimate use & responsibility

QWERTY is a tool for **legitimate multi-account management**: marketing agencies
handling many client ad accounts, QA and ad-verification testing, web-automation
development, and privacy research — the same use cases served openly by
commercial anti-detect browsers.

Do **not** use it for fraud, credential stuffing, spam, evading bans you've
earned, or anything that violates a site's terms of service or the law. You are
responsible for how you use it.

## License

[MIT](LICENSE) — free to use, modify and distribute.
