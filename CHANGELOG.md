# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- **One unreadable profile no longer hides every other profile.** `ProfileStore.list()`
  guarded only `JSONDecodeError`/`KeyError`, but a file written by a different
  version surfaces as `TypeError`/`ValueError`/`AttributeError` from the dataclass
  constructor — so a single drifted file emptied `qwerty list`, the dashboard grid,
  Health and collisions. Added `list_with_errors()` for when you need to know
  *which* files were skipped and why.
- **Concurrent schedule writes no longer clobber each other.** Every mutation was
  an unlocked read-modify-write of one JSON file while the API server ran the
  scheduler on a background thread. A 2-thread test lost 33 of 40 schedules;
  mutations now take a per-data-directory lock and the file is replaced
  atomically. `update()` also refuses to rewrite a schedule's `id`.
- **Pinning a Chrome version no longer resets every Android profile to one
  handset.** `build_user_agent(os, chrome)` could not express the device token,
  so bulk-create with `--chrome` (and `qwerty align`) rebuilt every phone's UA as
  the default model while its GPU, screen and RAM still described a different
  one — incoherent *and* a mass UA collision, and `validate()` did not catch it.
  Added `platform_token()` / `rebuild_user_agent()`, which carry the handset over.
- **The dashboard builds Android profiles as one real handset.** `uaFor()`
  hardcoded `Pixel 7`, and screen/GPU/cores/RAM were drawn independently. The UI
  now mirrors the engine's `ANDROID_DEVICES` table and draws a phone as a bundle.
- **The live coherence meter matches the engine.** It now checks cores *per OS*
  (a 128-core "phone" used to pass) and validates that a hand-edited Android
  User-Agent still names the handset the rest of the profile describes.
- **One unparseable cookie no longer aborts a whole import.** `normalize()`
  raised `ValueError` on a non-numeric `expirationDate` (ISO timestamps appear in
  real extension exports). Expiry is now coerced — ISO parsed, unusable values
  degraded to a session cookie — and non-finite values no longer serialise as
  bare `Infinity`, which is not valid JSON.
- **Proxy credentials are URL-encoded.** A password containing `/` ended the
  netloc early, so `user:pa/ss@host` parsed with `user:pa` as the host and a good
  proxy failed its health check.
- **Scheduled warm-ups fail loudly.** `_scheduler_tick` swallowed every exception
  silently, so a persistently broken tick was indistinguishable from "nothing was
  due". Failures are logged and isolated per schedule.
- Imports from GoLogin/AdsPower/Multilogin no longer invent a proxy from an
  export whose type is explicitly `none`; `bulk.select()` de-duplicates by id
  rather than by dataclass value-equality (two distinct profiles with identical
  fields collapsed into one).

### Fixed (second QA pass)
- **`navigator.deviceMemory` no longer reports a value no real Chrome can.**
  The Device Memory spec deliberately coarsens the property for privacy: clamped
  to `[0.25, 8]` and rounded to a power of two. QWERTY was injecting the
  machine's physical RAM, so profiles reported `6`, `12`, `16` or `32` — an
  instant, trivially-checked tell, and `validate()` did not flag it. The
  fingerprint keeps the real RAM (it is what the profile *is*); only what the
  page can see is coarsened, via `devices.reported_device_memory`.
- **`devicePixelRatio` matches the handset the user-agent names.** Every Android
  profile launched with a hardcoded `2.625`, contradicting the model it claimed —
  a Galaxy S22 Ultra reports `3.75`, a Pixel 6 `2.75`. `ANDROID_DEVICES` now
  carries a per-handset `dpr` and the launcher reads it back from the UA.
- **`qwerty attach` refuses an occupied port.** Chromium cannot bind a port
  already in use, so the DevTools probe answered from whatever browser *was*
  listening — and the caller's script then silently drove that unrelated session.
  Since `9222` is everyone's default, this was common rather than exotic.
- **Warm-up no longer spins when nothing is reachable.** A navigation can fail
  instantly (no DNS, no network) and the retry path skipped the human pause, so
  an offline machine hammered every site in the pool for the full duration.
  Failures now back off, and a run that reaches nothing at all stops early.
- **Dashboard profiles get a distinct font subset.** `to_engine_profile` handed
  every profile the complete OS font pool, so they were identical on a
  high-entropy signal — and unusually complete, since real machines rarely have
  every font. Now mirrors `fingerprint.generate`'s per-profile sampling, seeded
  from the profile's own seed so the list is stable across launches; the editor's
  Fonts mode (`Masked`/`Real`) finally reaches the engine. `collision.py` still
  does not compare fonts, which is why nothing caught this.

### Fixed (found by actually running it)
- **A profile missing any field blanked the entire dashboard.** `POST/PUT
  /api/profiles` stored the request body verbatim, while the UI assumes ~16
  fields exist (`p.tags.map(...)`, `p.browserVersion.split(...)`). A profile
  created by any other client went to a black screen with only a console
  message. Fixed at both layers: `normalize_dashboard_profile()` fills every
  field (and coerces nulls and wrong types) on read *and* write, so profiles
  already on disk are repaired too; and the UI gained an `ErrorBoundary` plus
  guards, so one unrenderable record can never take the whole app down again.
- **Launching an uninstalled engine reported success.** The launch runs in a
  subprocess whose exit code and stderr the endpoint never read, so asking for
  `cloak` without `cloakbrowser` returned HTTP 200 with status `"running"`, the
  child died in under a second, and the profile silently flipped back to
  `stopped`. Now preflights the engine (HTTP 400 naming the missing package) and
  surfaces the child's own error if it dies immediately.
- **The trust checker failed every 12/16/32 GB profile.** It compared the
  fingerprint's physical RAM against `navigator.deviceMemory`, which the spec
  caps at 8 — a direct consequence of coarsening that property. It now compares
  against the reportable form, so a correctly-spoofed profile grades A again.
- **`align` overwrote real RAM with a coarsened reading.** `navigator.deviceMemory`
  is lossy (anything >= 8 GB reads back as 8), so aligning permanently replaced a
  profile's 16 GB with 8 while learning nothing. It now only corrects the value
  when the stored RAM could not have produced the reading.
- **The default folder was the "show everything" sentinel.** Storing
  `"All profiles"` as a profile's folder made the sidebar render a phantom second
  "All profiles" row with a duplicate React key. Default is now `"Unsorted"`, and
  the folder list strips the sentinel regardless; the literal is now the
  `ALL_FOLDER` constant it should always have been.
- **Hint panels with inline icons rendered as jumbled columns.** `.ps-hint` was
  `display: flex`, making every child — including mid-sentence `<b>` and icons —
  its own flex item. The Health legend has three inline icons and was unreadable.

### Fixed (fresh-developer shakedown — every command exercised end to end)
- **A locked vault silently destroyed proxy passwords.** Reading with no (or the
  wrong) master password decrypts secrets to `None`, so `save()`'s
  "refuse to downgrade" guard — `any(self._secret_values(profile))` — never
  fired and that `None` was written straight over the ciphertext. An unrelated
  `qwerty edit --notes` permanently lost the password, unrecoverably. Locked
  saves now carry the on-disk ciphertext across untouched (so editing notes and
  tags without the password still works), while setting a *new* secret while
  locked is refused, which was the original intent.
- **The stealth script never reached the page `attach` hands you.**
  `add_init_script` applies from the next document onward, so the `about:blank`
  page a persistent context already has open kept the real
  `hardwareConcurrency`, an undefined `deviceMemory` and no `window.chrome` —
  and that page is exactly what `qwerty attach`'s own snippet tells you to use
  (`contexts[0].pages[0]`). Anyone sanity-checking their fingerprint before
  navigating saw their real machine. The script is now applied to already-open
  documents too.
- **`qwerty regen` silently changed the operating system.** It passed
  `os=args.os` (None → random), so regenerating a Windows profile could turn it
  into macOS — a severe discontinuity for a logged-in session, and it disagreed
  with `apply --regen` and duplicate-as-template, which both preserve the OS.
  `--os` / `--locale` remain as explicit overrides.
- **`qwerty proxy test` reported a red FAIL and exit 1 on a healthy profile.**
  The WebRTC leak check compared every public address against the observed exit
  IP, which *is* your real IP when going direct — so a benign IPv4/IPv6
  difference read as a leak. It now reports a baseline pass when no proxy is
  configured, matching how the DNS check names its own baseline case.
- **Deleting a profile orphaned its warm-up schedules.** They listed themselves
  as bare hex ids and were retried on every tick forever. Delete now cascades,
  from both the CLI and the API.
- **Cookie import over-reported.** It counted what was submitted, not what the
  browser kept — Chromium silently drops an already-expired cookie, so
  "Imported 3" could not be reconciled with the 2 that `cookies list` showed.
  It now counts what persisted and says how many were rejected.
- **Long-running commands printed nothing when piped.** Python block-buffers a
  non-tty stdout, so `serve`, `attach`, `warmup` and `schedule run-due` produced
  no output at all until they exited — exactly when progress matters most.
  stdout is now line-buffered.
- `qwerty list` columns were misaligned: the id was colourised *before* being
  padded, so the format width counted invisible ANSI bytes — off by one in a
  terminal and wildly wrong when piped. Long names now truncate instead of
  running into the next column.
- `qwerty edit` gained `--remove-tag` (it claimed to edit tags but could only
  add), and `--os` / `--locale` / `--chrome` / `--tag` now accept
  comma-separated values as well as repeated flags.
- `start.bat` sets `chcp 65001`, so the CLI's em-dashes don't become mojibake on
  the legacy code pages many Windows installs still default to.
- `vault enable` no longer points at a `vault change` command that never existed.
- DNS resolver country codes are upper-cased ("3 in IN", not "3 in in").

### Changed
- The `dev` extra installs FastAPI/Uvicorn so the API tests run in CI.
- `session.analyze()`'s `status` precedence is unchanged and now documented:
  it names the most *actionable* condition, not the most severe. Use the
  `expired` / `expiringSoon` counts when you need severity.

### Security
- **Path traversal in `restore()` (zip-slip)**: a backup archive is designed to
  travel between machines, so it has to be treated as untrusted input. An entry
  named `user-data/../../../evil` previously wrote *outside* the profile's
  user-data directory. Every target path is now resolved and checked for
  containment **before** any byte is written, so a hostile entry raises
  `UnsafeArchive` and aborts the whole restore instead of leaving files
  half-extracted. Absolute paths and Windows drive-letter paths are rejected too.
- **Wildcard CORS on the API**: `qwerty serve` binds to localhost, but that never
  stopped a page you had open from calling it cross-origin — with
  `allow_origins=["*"]`, any website could enumerate profiles, read decrypted
  proxy passwords, launch browsers or delete everything while the engine ran.
  The allow-list is now the dashboard's own localhost dev/preview origins,
  overridable with `QWERTY_ALLOWED_ORIGINS` or `qwerty serve --allow-origin URL`.
  `serve` prints the active policy on startup.
- The `dev` extra now installs FastAPI/Uvicorn so the CORS regression tests
  actually execute in CI instead of silently skipping.

### Changed
- **Renamed the project to QWERTY Studio.** The Python package is now `qwerty`,
  the CLI command is `qwerty` (`python -m qwerty` still works), the data
  directory is `~/.qwerty`, and the environment variable is `QWERTY_PASSWORD`.
  The distribution is `qwerty-engine`; the dashboard is `qwerty-dashboard`.
  Existing data under `~/.persona` is **not** migrated automatically — move the
  directory to `~/.qwerty` (or point at it with `--data-dir`) to keep your
  profiles. The vault verifier constant is deliberately unchanged so an existing
  vault still unlocks with the same master password once its data dir is moved.

### Added
- **Mobile (Android) profiles**: fingerprint generation now assembles a whole
  handset — the model in the User-Agent (`Pixel 7`, `SM-G991B`, …), the Android
  version, the GPU, screen and RAM all describe one real phone rather than mixed
  parts. Launch adds touch support and a phone device-scale factor. Android was
  already selectable in the dashboard; it's now coherent end-to-end.
- **Session health** (`qwerty session <ref>` / `POST /api/profiles/{id}/session`):
  reads the profile's real cookie jar and reports how many cookies are expired or
  expiring within a week, and which services still have a live login (Facebook,
  Instagram, Google, X, LinkedIn, …). Surfaced as a badge and per-row check on the
  **Health** page, and a **Session** tab in the profile editor. Cached as
  `_session` so the Health grid shows it without re-opening every profile;
  stale / expiring sessions now count toward "needs attention".
- **Duplicate as template** (`POST /api/profiles/{id}/duplicate`, the ⧉ card
  action): clones a profile's settings (proxy, folder, tags, notes, engine,
  startup URLs, OS + locale) but re-rolls the fingerprint, so the copy is a
  genuinely different device instead of a fingerprint twin that a site could link
  back to the original.
- **Per-profile activity log** (`GET /api/profiles/{id}/activity`, editor
  **Session** tab): records launches, session ends, warm-ups, trust runs,
  auto-adjusts, cookie imports and session checks as a timeline.
- **Folders manager** (dashboard **Folders** tab): create, rename and delete
  folders, each shown as a card with live profile / running / coherent counts and
  one-click open. Folders are persisted server-side (`GET /api/config` →
  `folders`, plus `POST /api/folders`, `…/folders/rename`, `…/folders/delete`), so
  an empty folder survives a reload; renaming or deleting one moves the profiles
  inside it (delete reassigns to *Unfiled*) rather than dropping anything. The
  editor, bulk-edit and sidebar dropdowns now read this live list.
- **Settings page** (dashboard **Settings** tab): theme toggle, the default launch
  engine for new profiles (persisted via `PUT /api/config`, with an "not
  installed" hint per engine), the on-disk storage location and a data summary
  (profiles / folders / proxies), and an about card. `GET /api/config` now also
  returns `root` and `version`.
- **Command palette** (dashboard, ⌘K / Ctrl-K): fuzzy-search across views,
  actions (new profile, toggle theme) and every profile (open / launch / stop),
  driven entirely from the keyboard (↑/↓/Enter, Esc to close).
- **Light / dark theme** (dashboard): a Sun/Moon toggle in the top bar switches
  the whole app between a new light theme and the original dark one; the choice
  is remembered in `localStorage`. The palette repaints inline styles, icons and
  the full stylesheet in one pass.
- **Toast notifications** (dashboard): success / error / info actions now surface
  as stacked, auto-dismissing toasts instead of blocking `alert()` popups.
- **Headless attach** (`qwerty attach --headless`, `POST …/attach {headless}`):
  attach a profile's DevTools endpoint without opening a visible window — for
  servers and CI. Exposed as a checkbox on the Automation page.

### Fixed
- **Auto-adjust capped at grade B** — `align` matched everything to the browser
  *except the timezone*, so on an engine that shows the host clock (e.g.
  CloakBrowser) the "timezone matches" check stayed failed forever, holding the
  grade at B (15/16). Align now follows the machine's real timezone and moves
  the locale to the coherent one for that zone (e.g. `Asia/Karachi` → `en-PK`),
  so a fully-aligned profile can reach A. Only moves the timezone when a locale
  models it, so coherence never regresses.
- Coherence's language check now compares the **base** language (`en`), not the
  region (`en-US` vs `en-PK`): an English browser in a Karachi timezone is a
  real, coherent user and shouldn't be flagged. A genuine mismatch (`de` vs
  `en`) is still caught.

### Changed
- Automation attach now reports success as a toast (with the port and whether it
  came up headless).

### Added (earlier this cycle)
- **Automation page** (dashboard, `POST /api/profiles/{id}/attach`): the engine
  already spoke CDP (`qwerty attach`) — now the dashboard drives it. One click
  opens a profile with a DevTools endpoint and hands back the connection details
  with ready-to-paste **Playwright / Puppeteer / Selenium** snippets (copy
  buttons, language tabs), so your script attaches to the *same* spoofed,
  warmed-up window instead of launching a fresh un-spoofed one. Detach = stop.
  Chromium engines only (cloak / patchright / playwright); the endpoint rejects
  Firefox-based camoufox with a clear message.
- **Fingerprint collision detector** (`qwerty collisions`, `collision.py`,
  `GET /api/profiles/collisions`): finds profiles that present the *same*
  fingerprint — identical WebGL, screen, hardware and user-agent read as one
  device wearing two hats, so a site can link the accounts and ban them
  together. Pure logic over the stored profiles (no browser), flagged on the
  dashboard **Health** page with a "Shared FP" count and a per-row badge, plus a
  CLI table. `identical` marks the worst case (same canvas/audio seed too).
- **Backup & restore** (`qwerty backup` / `qwerty restore`,
  `ProfileStore.backup`/`restore`): zip a profile **and its whole browser
  session** (cookies, localStorage — everything under user-data) into one
  portable file to archive it or move it to another machine. `restore --new-id`
  brings it in as a fresh copy instead of overwriting the original. (Unlike
  `export`/`import`, which move only the config.)
- **Bulk grid actions & tag filtering** (dashboard): the multi-select bar now
  also **warms up** and **exports** the selected profiles in one go (alongside
  the existing launch / edit-all / delete); the filter popover gained a **Tag**
  filter, and tags shown on a profile are clickable to filter by them.
- **Profile health overview** (`GET /api/profiles/health`, dashboard **Health**
  page): one row per profile grading it at a glance — coherence (computed
  instantly from the stored fingerprint), whether a proxy is set and its country,
  the last measured trust grade (cached from the last trust/align run, since a
  live check opens a real browser), any warm-up schedule, and last-active. Rows
  that need attention (incoherent, or a C/D trust grade) are flagged, with
  one-click **trust check** and **auto-adjust** per row.
- **Scheduled warm-up** (`qwerty schedule`, `scheduler.py`, `/api/schedules*`):
  recurring, unattended warm-up so a session you log into once doesn't go
  "cold". Add a schedule per profile (interval + vertical); when `qwerty serve`
  is running a background thread fires the due runs itself, and for people who
  don't run the server, `qwerty schedule run-due` runs whatever's due from cron
  / Windows Task Scheduler. Exposed in the dashboard's Warm-up section as a
  toggle with interval and vertical controls.
- **Warm-up presets per vertical** (`qwerty warmup --preset`, `warmup.PRESETS`):
  `ads`, `ecommerce`, `crypto`, `social`, `news` (or the default `general`) each
  browse a site set that matches the account's world, so its history reads like
  a real user of that vertical rather than a random walk. Chosen from a dropdown
  in the dashboard; passed through `POST /api/profiles/{id}/warmup`.
- **DNS leak checker** (`qwerty dns`, `probe.check_dns`,
  `/api/profiles/{id}/dns`): the companion to the proxy test — even with the
  proxy hiding your IP, DNS lookups that go to your own ISP's resolver still
  reveal the sites you visit at your real location. It resolves a batch of
  unique subdomains through the profile, reads back which resolvers were seen
  (and their countries) from a third-party test service, and fails if any sits
  outside the proxy's country. Folded into `proxy test` and surfaced as a **DNS
  leak test** button next to the connection test in the dashboard.
- **Proxy pool — import, test, assign** (`proxypool.py`, `/api/proxies*`):
  a managed pool the dashboard's Proxies page now drives for real. Import a
  pasted list or file in any common layout (`host:port`, `host:port:user:pass`,
  `user:pass@host:port`, `scheme://…`, optional trailing country code),
  health-check each one over HTTP(S) without a browser (exit IP/country/latency),
  and **assign them round-robin across profiles** — which also aligns each
  profile's locale/timezone to its proxy's country. Bulk-created profiles start
  proxy-less and get real proxies from here, instead of the old placeholder
  hosts.
- **Dashboard-side import** (`/api/profiles/import`, `to_dashboard_profile`):
  the GoLogin / AdsPower / Multilogin importer is now wired to an **Import**
  button in the dashboard — pick an export file, and each profile is mapped to a
  coherent identity, saved, and flagged for review if anything didn't line up.
  (Previously the importer lived in the CLI/engine store only.)
- **Auto-adjust — align a profile to reality** (`qwerty align`, `probe.py`):
  a one-click fix for a low trust grade. It opens the profile, reads back what
  the browser *actually* presents (platform, CPU, memory, GPU, screen, fonts,
  media, languages) and rewrites the fingerprint to match — regenerating the OS
  identity when the engine turns out to render a different OS than the profile
  claimed (e.g. CloakBrowser showing the host's real hardware). Afterwards the
  browser and the profile tell one story, so a detector sees no contradiction;
  the trust score jumps to A. Exposed as `POST /api/profiles/{id}/align` and an
  **Auto-adjust** button next to the trust check, which pulls the rewritten
  values straight back into the editor and shows the before→after grade.
- **Bulk create at scale** (`qwerty bulk-create`, `bulk.generate_profiles`,
  `POST /api/profiles/batch`): generate thousands of coherent profiles at once —
  up to 10,000 from the dashboard — spread across operating systems, countries/
  locales and Chrome versions, each with its own seed so no two share a
  fingerprint. The dashboard's bulk dialog gained OS/country/browser multi-pick,
  an engine choice, a randomize-hardware toggle and a per-country proxy switch,
  and posts in chunks; the profile grid is now **paginated** so a 10k list stays
  responsive.
- **Real GPUs and displays count as coherent.** `validate()` (and the dashboard
  meter) now accept any WebGL renderer whose graphics API fits the OS (Windows →
  Direct3D, macOS/Linux → desktop OpenGL) and any real-world screen size, not
  just the short curated lists — so a machine-aligned profile carrying its
  actual GPU/resolution isn't wrongly flagged. `navigator.languages` is matched
  on its primary language rather than an exact list.
- **Import from other anti-detect browsers** (`qwerty import-from`,
  `importers.py`): migrate profiles exported from GoLogin, AdsPower or
  Multilogin. Tolerant field mapping (each value looked up under its known
  aliases), gaps filled from a coherent generated base, and every imported
  profile run through `validate()` so mismatches are flagged for review rather
  than shipped silently.
- **Encrypt-at-rest for secrets** (`qwerty vault`, `crypto.py`): a master
  password encrypts proxy passwords in the store (Fernet/AES, key via
  PBKDF2-HMAC-SHA256), leaving the rest of each profile readable. Supply the
  password via `QWERTY_PASSWORD` or `--password` at use time so it never hits
  disk; locked stores still list/manage profiles but withhold the secret, and
  saving would-be-plaintext over an encrypted secret is refused. Optional
  `[secure]` extra; degrades gracefully when it isn't installed.
- **TLS/JA3 handshake checker** (`qwerty tls`, `probe.py`): reads the profile's
  own TLS/HTTP2 handshake back from an echo service and reports its JA3 and JA4
  fingerprints — the network layer JavaScript can never touch, since the server
  sees it before any page script runs. Checks it negotiates TLS 1.3 + HTTP/2 and
  sends GREASE like a real Chromium. Folded into `proxy test` too, plus
  `POST /api/profiles/{id}/tls` and a button in the dashboard.
- **Fingerprint trust checker** (`qwerty trust`, `probe.py`): opens the profile
  and runs the checks a fingerprinting script runs — webdriver, plugins, UA vs
  platform, WebGL, timezone, font probing, media devices, canvas stability — then
  scores the result. Grades the real browser, where `qwerty check` grades the
  config. Also `POST /api/profiles/{id}/trust` and a button in the dashboard.
- **Proxy tester + WebRTC leak checker** (`qwerty proxy test`): routes a real
  request through the profile, reports the exit IP/country/timezone and whether
  they agree with the identity, then checks whether WebRTC exposes an address the
  proxy was meant to hide. Wires up the dashboard's "Test connection" button.
- **Multi-profile synchroniser** (`qwerty apply`, `bulk.py`): one change applied
  to many profiles, selected by name, `--tag` or `--all`. Unmentioned fields are
  left alone; changing the locale moves timezone and languages with it. Exposed as
  `POST /api/profiles/bulk` and "Edit all" in the dashboard's selection bar.
- **Account warm-up** (`qwerty warmup`, `warmup.py`): browses ordinary sites at
  human pace so a fresh profile doesn't arrive with an empty history.
- **Local automation API** (`qwerty attach`, `automation.py`): launches the
  profile with the DevTools protocol open and prints connect snippets, so
  Selenium/Puppeteer/Playwright drive *that* browser — identity, proxy and
  session intact.
- **Extensions manager**: per-profile unpacked extensions (`qwerty ext
  add|list|remove`, `Profile.extensions`, dashboard field). Only the profile's own
  extensions load, so nothing carries between profiles.
- **More fingerprint signals**: per-OS installed fonts (answered by
  `document.fonts.check`), camera/microphone counts via `enumerateDevices` with
  seeded stable ids, sub-pixel ClientRects jitter, and seeded audio noise. Fonts
  and media counts are covered by `validate()` too.
- **Cookie import/export** (`qwerty/cookies.py`): move a logged-in session
  between machines or seed a fresh profile with one you already have. Reads
  Cookie-Editor / EditThisCookie JSON, Playwright storage state and Netscape
  `cookies.txt`; writes JSON or `cookies.txt`. Available as
  `qwerty cookies list|export|import`, `GET`/`POST /api/profiles/{id}/cookies`,
  and Import/Export buttons in the dashboard's **Advanced** tab.
- **One-click Windows launcher** (`start.bat`): double-click to install deps on
  first run, pick the default engine (CloakBrowser first), then start the engine
  API + dashboard and open the browser.
- **Persisted default engine** for new profiles (`config.json`): `qwerty
  default-engine [name]` command, `GET`/`PUT /api/config` endpoints, and the
  dashboard defaulting new profiles to it. CloakBrowser is the top-priority
  default, and the last engine you pick "wins" (becomes the next default).
- **HTTP API** (`qwerty serve`, `engine/qwerty/server.py`) wrapping the store,
  validator and launcher so the dashboard can manage and launch profiles for real.
- **`python -m qwerty`** entry point (`qwerty/__main__.py`).
- Dashboard **live/demo mode**: connects to the engine API when available
  (launching opens a real browser), falls back to sample data when it isn't.
- **Pluggable launch engines** (`qwerty/drivers.py`): choose a stealth backend
  per profile — `playwright` (built-in), `patchright`, `camoufox`, or `cloak`
  (CloakBrowser). New `qwerty engines` command, `--engine` flag, `Profile.engine`
  field, dashboard engine selector, and `GET /api/engines` endpoint.
- **Dashboard redesign**: new "ink violet" theme, Space Grotesk / Inter / JetBrains
  Mono typography, motion (load reveals, status pulses, drawer slide), and a
  dedicated **Engines** page recommending CloakBrowser & Camoufox with one-click
  install commands. Reduced-motion respected.

### Changed
- **Geolocation now agrees with the proxy.** Launches set
  `navigator.geolocation` to coordinates for the proxy's country (or the
  locale's, without a proxy) and pre-grant the permission, so a site that asks
  gets coordinates that match the exit IP instead of a US timezone with German
  GPS. New `devices.COUNTRY_GEO` / `LOCALE_TO_COUNTRY`.
- **WebRTC IP handling is enforced at launch.** With a proxy, non-proxied UDP is
  disabled (`disable_non_proxied_udp`) so WebRTC can't bypass it; without one,
  only the public interface is exposed so local IPs stay hidden.
- **Hardened the stealth script**: `navigator.webdriver` now reads `false` from the
  prototype (not an own property), `window.chrome`, realistic `navigator.plugins`/
  `mimeTypes` (native `PluginArray`), consistent `permissions.query`, and native
  `toString()` on all patched functions — passing BrowserScan's basic checks.
- `launcher.py` is now a thin dispatcher over `drivers.py`.

### Fixed
- **Canvas and audio noise are now stable across reads.** Both drew from a single
  advancing PRNG and mutated the caller's canvas/buffer in place, so reading the
  same canvas twice gave different bytes — itself a detection signal (CreepJS
  checks for exactly this). Each source now restarts from the profile seed and
  works on a copy.
- **`enumerateDevices` spoofing actually applies.** It was building device objects
  with `Object.assign` against getter-only `MediaDeviceInfo` properties, which
  threw and silently fell back to Chromium's real list. Found by the new trust
  checker.
- **Startup URLs are now opened** on launch (first in the main tab, the rest in
  new tabs) instead of always landing on `about:blank`.
- **Launch button no longer sticks on "running"** after you close the browser
  yourself — the dashboard polls run status in live mode and flips back to start.
- **"Last active" now updates** (server records when a session ends and shows a
  relative time) instead of always reading "never".
- **New profiles no longer overwrite an existing one** — the server assigns each
  profile a unique id, and the local id generator is collision-resistant.
- Suppressed Chromium's infobars: the "controlled by automated test software"
  bar (Playwright) and the cosmetic "--no-sandbox unsupported flag" bar
  (CloakBrowser, via `--test-type` — invisible to websites).
- `qwerty launch --headless` no longer hangs forever waiting for a window that
  never opens.

## [0.1.0] - 2025

### Added
- **Engine**: coherent fingerprint generator (device-archetype approach) with
  `validate()`; `Fingerprint`/`Proxy`/`Profile` models; JSON-per-profile store
  with import/export and persistent user-data dirs; stealth init-script
  generator; Playwright launcher with proxy support; full CLI.
- **Dashboard**: React web console with profile grid, tabbed fingerprint editor,
  live coherence meter, proxy manager, bulk create, folders, tags, search.
- Monorepo layout, CI, docs, and contribution guides.
