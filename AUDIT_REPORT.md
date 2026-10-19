# OmniCat – Audit Report

**Date:** 2026-10-12 · **Branch audited:** `dev` @ `a22f8e6` · **Phase:** 1 (read-only; no code changed for this report)

Severity: **Critical** = exploitable now / data loss · **High** = serious risk or broken core flow · **Medium** = real defect, limited blast radius · **Low** = hygiene.
Effort: **S** < 1 h · **M** 1–4 h · **L** 0.5–2 days.

> This audit follows three fix rounds made earlier in this session (commits `b84a838`, `a2f93f0`, `2e5e423`, `a22f8e6`). Issues already fixed are listed in §0 and are **not** repeated as findings.

---

## 0. Already fixed earlier in this session

| Commit | What |
|---|---|
| `b84a838` | Postgres tz crash on every `/auth/refresh` + permanent lockout; 2FA usable without password; refresh token accepted as access token; task IDOR (status/cancel/SSE); cross-user deletion of cached files; per-user rate-limit key; Google login hardening; session revocation on password reset/change; Excel formula injection; frontend infinite refresh loop + refresh race |
| `a2f93f0` | URL cache moved to Postgres (shared across workers); thread-pool leak; streamed upload size check; CSV export formula injection; test email removed from allowlist |
| `2e5e423` | `/api/analytics/*` was fully unauthenticated (read / inject / delete) |
| `a22f8e6` | WCAG 2.1 AA pass (axe: 70+ violations → 0 on 14 views), accessible modals, invisible upload errors, mobile dashboard overflow, analytics token expiry, error boundary |

---

## 1. Architecture overview

**What it is.** OmniCat is an internal tool for IN2 Communications staff. A user uploads an Excel file of social-media comments, or pastes a post URL (Facebook, Instagram, YouTube, TikTok, X). The comments are exported via the ExportComments API, and each comment is translated to English and classified (sentiment + category) by Google Gemini. The user gets a processed Excel file, sentiment counts and AI-written summaries per sentiment. Admins manage users, projects and invitations; "dashboard users" see usage analytics.

**Users and roles** (`backend/bootstrap.py:57-82`): `basic_user` (analyze, own history), `dashboard_user` (+ analytics, audit), `admin` (+ users, projects, invitations). Sign-up is invite-only by email link, or Google sign-in for whitelisted domains (`backend/utils/whitelist.py`).

| Layer | Stack |
|---|---|
| Frontend | React 18 SPA, Vite 6, Tailwind v4, react-router 7, axios; charts: recharts **and** MUI x-charts; served by nginx with CSP (`frontend/default.conf.template`, `docker-entrypoint.sh`) |
| Backend | FastAPI 0.115 on gunicorn + UvicornWorker (2 workers), SQLAlchemy 2.0, slowapi, python-jose JWT, passlib/argon2, pyotp |
| Database | PostgreSQL (prod/staging), SQLite (tests). Schema via `Base.metadata.create_all` at startup (`backend/database.py:73`); **no migration tool** |
| Background work | In-process only: FastAPI `BackgroundTasks` (URL extraction), bare `asyncio.create_task` (uploads, `api/routes/upload.py:159`), hourly cache-cleanup coroutine (`main.py:62`). No queue, no worker process |
| External services | Google Gemini (`services/gemini_service.py`), ExportComments SDK (`services/export_service.py`), Resend email (`utils/email_service.py`), Google Identity Services |
| Auth | HttpOnly cookie JWT (15 min access / 30 day rotating refresh), CSRF double-submit, optional TOTP 2FA |
| Deploy | GitLab CI builds images (`.gitlab-ci.yml`), server pulls by image watching; `docker-compose.yml` (+ overlays); TLS at a host reverse proxy (not in repo) |

**Entry points.** SPA routes (`frontend/src/App.jsx`): `/login`, `/register?token=`, `/forgot-password`, `/reset-password?token=`, `/app` (main tool), `/profile`, `/dashboard` (needs `view_dashboard`). The API has 67 routes under `/api` (auth, users, admin, projects, activity-logs, upload, extraction, tasks, analytics, progress SSE, download), plus `/`, `/health`, `/test` and `/config.js`.

**Core journeys.** (1) Accept invite → register → land on `/app`. (2) Log in (± 2FA / Google). (3) Upload a file or paste a URL → choose a project → watch progress (SSE) → results + download. (4) History of past results (stored in the browser's localStorage). (5) Profile: change password, 2FA. (6) Dashboard: analytics, sessions, activity log; admin: projects, team, invitations.

**Recent history.** 50 commits. Original import on 2026-05-20, a large security-remediation burst on 05-22 and 05-25 (H1–H12, M1–M12 from `docs/SECURITY_ASSESSMENT.md`), and this session's 4 commits on 10-12. The 05-25 cookie migration (`764e275`) introduced the regressions fixed in `b84a838`: the rate-limit key falling back to IP, the refresh loop, and missing CORS for the CSRF header.

---

## 2. Findings

### E. Security and privacy (listed first, as it is fixed first)

| ID | Sev | Evidence | Impact | Fix |
|---|---|---|---|---|
| E1 | **Critical** | Google API key (`AIzaSyBY…`) committed in `README.md` in `570a090`; still in history (removed in `9e85778`/`562d7d9`). Value not reproduced here | Anyone with repo access, now or in the past, can use the key (likely Gemini → billing abuse and quota exhaustion) | **Rotate the key in Google Cloud now.** Optionally purge it from history (`git filter-repo`), but rotation is what matters |
| E2 | High | `docker-compose.prod.yml:6-7` publishes Postgres on `${HOST_DB_PORT}` on all host interfaces | The DB is reachable from the network unless a host firewall blocks it. Can't verify the server's firewall from the repo | Remove the `db` port mapping, or bind to `127.0.0.1:` only |
| E3 | High | Backend `pip-audit`: **aiohttp 3.12.15 (32 advisories, fixed 3.14.3)**, **starlette 0.41.3 (7, via fastapi 0.115.6)**, **python-multipart 0.0.12 (7)**, **python-jose 3.3.0 (3)** + ecdsa (no fix), requests (2), python-dotenv, setuptools, pytest | Known DoS / parsing / JWT issues in internet-facing code paths (multipart upload parsing, Starlette routing, outbound aiohttp) | Upgrade fastapi (pulls starlette), python-multipart, aiohttp, requests, python-dotenv. Replace python-jose with PyJWT (also removes ecdsa). Re-run the tests |
| E4 | High | Frontend `npm audit`: 19 (2 critical, 11 high). Runtime: axios, react-router(-dom), form-data, nanoid, postcss, vite, source-map-js. Critical ones (vitest, tinypool) are dev-only | axios / react-router advisories ship to users | `npm audit fix` (non-breaking set); vitest 5 is a major upgrade, so do it separately |
| E5 | Medium | `utils/whitelist.py:5-21`: personal staff emails hard-coded and used for role assignment on first Google login | PII in source; access changes need a code deploy; any `@in2-comms.com` Google account self-provisions as `basic_user` | Move to env/DB config (or an admin-managed allowlist). Confirm domain self-signup is intended |
| E6 | Medium | `/api/info` (`api/routes/__init__.py:119`) and `/api/health` are public and return a full (stale) endpoint map. `/health` (`main.py:520`) returns task and cache stats; `/test` (`main.py:262`) is public | Reconnaissance aid; minor info leak | Remove `/api/info`, `/api/health`, `/test`; reduce `/health` to `{"status":"ok"}` |
| E7 | Medium | Rate limits are in-memory per worker (`utils/rate_limit.py`, docstring) | Real limit is ×2 with 2 workers; it resets on restart | Accept, or point slowapi `storage_uri` at Redis (the only reason to add Redis). Low priority |
| E8 | Medium | **Privacy / retention:** `activity_logs` keeps IP + user agent forever (`models/activity_log.py`); `tasks.result_data` keeps AI summaries forever (`task_manager.py:9` "keep-forever"); uploaded files and outputs under `uploads/<email>/` are never deleted (only URL-cache files expire); user deletion cascades and **erases that user's audit log** (`models/activity_log.py:11`, `routers/admin.py:155`) | Indefinite storage of personal data: staff IPs and third-party commenter names, profile URLs and avatars inside uploaded and exported files. Comment text is sent to Google Gemini (processor) | Define retention (e.g. logs 180 d, uploads/results 90 d) with a daily cleanup job. Use `SET NULL` instead of cascade for logs. Document Gemini/ExportComments as processors. **Needs your policy decision** |
| E9 | Low | `README.md` history (`570a090`) contains a `DATABASE_URL` with a password for `localhost` | Only a risk if that password is reused anywhere | Make sure it isn't reused |
| E10 | Low | `utils/email_service.py:36` sends from `onboarding@resend.dev` | Resend's test sender only delivers to the account owner, so password reset probably can't work for users. Likely why the "Forgot password" link is commented out (`Login.jsx:239`) | Verify a sending domain in Resend, then re-enable the link (see U6) |
| E11 | Low | `frontend/public/config.js:2-3` commits the staging API URL + Google client ID (the entrypoint overwrites them in Docker) | Not a secret (client IDs are public), but a stale environment value in the build | Replace with empty placeholders |

Verified OK: no `dangerouslySetInnerHTML` / `eval`; SQL access is ORM-only (no raw string SQL); path traversal guarded (`utils/paths.py`); SSRF guard on download fetches (`utils/url_safety.py`); CSRF double-submit + SameSite=Lax; CSP at nginx; Swagger disabled in prod; secrets only from env; CI uses dummy keys.

### D. Backend correctness, performance and reliability

| ID | Sev | Evidence | Impact | Fix |
|---|---|---|---|---|
| D1 | High | ExportComments SDK is **synchronous** and called inside async code: `export_service.py:254` (`jobs.create`) and `:282` (`jobs.check`, every 10 s for up to 2 h). Also `pd.read_excel` / `to_excel` run on the event loop (`:411`, `:537`) | Each call blocks the whole worker's event loop: every request on that worker stalls, SSE progress freezes, health checks can time out | Wrap with `await asyncio.to_thread(...)` (stdlib, no new deps) |
| D2 | High | Tasks run in-process. Nothing marks running tasks as failed after a restart (`main.py:76` lifespan); the "one active task per user" rule (`upload.py:69`, `main.py:427`) then makes the user resume a task that will never finish | After every deploy or crash, users with an in-flight job are stuck at a frozen progress bar until they find "Cancel" | On startup, mark `extracting/processing` tasks older than N minutes as `failed: "Interrupted by server restart"` |
| D3 | High | Comments the AI fails on (after 5 retries) are **silently dropped**: `gemini_service.py:490-491` returns `(text, None)`; `processing.py` skips them; `file_utils.py:82-90` filters invalid sentiments | Results and counts under-report with no warning (data-quality / trust issue) | Return and show "X of Y comments could not be analyzed"; keep them in the Excel with `Sentiment = "unanalyzed"` |
| D4 | Medium | `asyncio.create_task(process_file_with_progress(...))` without keeping a reference (`upload.py:159`) | Python docs: unreferenced tasks can be garbage-collected mid-run (rare but real) | Keep a module-level `set` of tasks with `add_done_callback(discard)`, or use `BackgroundTasks` like the URL path |
| D5 | Medium | No timeout on Gemini calls (`gemini_service.py:211-226`; `settings.request_timeout` is defined but unused, `config.py:79`). Executor of 150 threads (`:122`) | A hung HTTP call holds a thread and a job forever | Pass `HttpOptions(timeout=…)` and wrap the wait with `asyncio.wait_for` |
| D6 | Medium | Global 120 s request timeout (`main.py:218`) also applies to uploads (up to 50 MB) | Slow connections get `408` mid-upload | Exempt `/api/upload/process` or raise its limit |
| D7 | Medium | **No migrations**: schema via `create_all` (`database.py:73`), which never alters existing tables or adds indexes to them | Any column or index change needs manual SQL in prod | Add Alembic with a baseline revision (justified by your migration requirement), or idempotent `CREATE INDEX IF NOT EXISTS` steps in `bootstrap.py`. **Your choice; I recommend Alembic** |
| D8 | Medium | Missing indexes: `activity_logs.user_id` (`models/activity_log.py:11`, filtered on every activity query + `ORDER BY created_at`), `refresh_tokens.user_id` (`models/refresh_token.py:10`), `usage_records.client_id` | Sequential scans as tables grow, and logs grow forever (E8) | Add `(user_id, created_at DESC)` and `refresh_tokens(user_id)` via migration |
| D9 | Medium | `docker-compose.prod.yml` / `.staging.yml` override services `db`, `backend`, `frontend`, but `docker-compose.yml` defines `omnicat-staging`, `omnicat-web-staging`, `omnicat-staging-db` | Using the overlays creates broken ghost services; the base file is staging-specific. I can't tell from the repo how prod is actually started | Align the service names, or delete the overlays and document the real deploy |
| D10 | Medium | Analytics aggregates in Python over all rows in range (`simple_analytics.py:53` loads every `UsageRecord`) and buckets by server local time (`datetime.fromtimestamp`) | Slows linearly with usage; day boundaries depend on the container's TZ | `GROUP BY` in SQL; bucket in UTC |
| D11 | Low | Inconsistent error shapes: `{"detail": …}` (FastAPI) vs `{"error": …}` (`main.py:226,230`, `/health`) vs `{"success": False, "error": …}` (`extraction.py:455`); many 500s echo `str(e)` (`upload.py:185`, `extraction.py:209`, `main.py:455`) | Harder client handling; leaks internals | Standardise on `{"detail": msg}`; log the exception, return a generic message |
| D12 | Low | N+1 queries: admin user list (`routers/admin.py:44`, roles → permissions per user); `activity_log_to_response` loads `log.user` lazily | Fine at current size; grows with users and logs | `selectinload(User.roles).selectinload(Role.permissions)`; `contains_eager(ActivityLog.user)` |
| D13 | Low | `ActivityLog.created_at` is a naive `DateTime` (`models/activity_log.py:18`) while every other table is tz-aware | The same tz-comparison class of bug as the one fixed in `b84a838` | Make it `DateTime(timezone=True)` via migration |
| D14 | Low | `config.py:213` prints at import; `main.py:34,37` print mode banners | stdout noise in logs | Use the logger |
| D15 | Info | Test coverage: backend has 255 tests, focused on auth/security; **none** for `processing.py`, `export_service.py`, `gemini_service.py`, `file_utils.py` (the core pipeline). Frontend has 2 smoke tests that render nothing from the app | Pipeline regressions go unnoticed | Add pipeline tests with a mocked Gemini/ExportComments; add CI lint + `npm audit`/`pip-audit` jobs |

**Frontend performance**

| ID | Sev | Evidence | Fix |
|---|---|---|---|
| D16 | Medium | Single JS chunk of **1.68 MB (475 KB gz)** (`vite build`). Dashboard + recharts + MUI ship to every user, including basic users | `React.lazy` for `/dashboard` and `/profile`; drop the unused UI libs (C2) |
| D17 | Medium | Images: `background.png` 722 KB on every page, `Omi_cat_logo.png` 192 KB shown at 32–240 px, `sample_input.png` 162 KB | Convert to WebP/SVG and resize: roughly 1 MB less per first visit |

### C. Accessibility (WCAG 2.2 AA)

After `a22f8e6`, axe-core reports **0 violations** on 14 views at 1280 px. Keyboard dialog behaviour (focus moves in, is trapped, Escape closes, focus returns) passes. Remaining items need WCAG 2.2-specific or manual checks:

| ID | Sev | Criterion | Evidence | Fix |
|---|---|---|---|---|
| A1 | Medium | 2.4.11 Focus Not Obscured (new in 2.2) | Sticky navbar `Navbar.jsx:28` (64 px) can cover elements focused while tabbing backwards | `html { scroll-padding-top: 5rem }` |
| A2 | Medium | 2.4.1 Bypass Blocks | No skip link anywhere | "Skip to main content" link as the first focusable element |
| A3 | Medium | 2.4.2 Page Titled | `index.html:18` sets "OMNICAT" for every route | Set `document.title` per route ("Sign in – OmniCat", …) |
| A4 | Medium | 4.1.2 Name, Role, Value | The mobile filter toggle in analytics is icon-only and unnamed (`EnhancedDashboard.jsx:142`); missed by axe because the scan ran at desktop width | `aria-label` + `aria-expanded` |
| A5 | Medium | 1.1.1 Non-text content | Analytics charts (recharts line/bar/pie) have no text alternative except the project table; the time-series chart has none | Add a visually-hidden data table or summary per chart |
| A6 | Low | 1.3.1 Info and relationships | Analytics `<table>` has no `<caption>`, and `<th>` has no `scope` (`EnhancedDashboard.jsx:397-408`) | Add `caption` + `scope="col"` |
| A7 | Low | 1.4.10 Reflow | Checked at 375 px: OK. Not checked at 320 px or 400 % zoom. Results pie chart has a fixed `width={400}` (`Graphs.jsx:100`) | Make the chart responsive, then re-check at 320 px |
| A8 | Low | 2.5.8 Target Size (new in 2.2) | Spot-checked buttons are ≥ 24 × 24 px. No full measurement done | Verify with a script during Phase 2 |
| A9 | Low | 1.3.1 / bidi | Users paste Arabic post text and filenames; inputs and lists have no `dir="auto"` | `dir="auto"` on the post-context textarea and filename/project text |
| A10 | Info | Manual | Not yet tested with real screen readers (VoiceOver / NVDA) | Manual pass on the core journeys |

The UI is English-only with no i18n, so a full RTL layout review doesn't apply. Only A9 (user-entered mixed-direction text) does.

### B. UI / UX

Walkthrough at 1280 × 900 with mocked data (screenshots taken during the audit):

| ID | Sev | Journey | Evidence | Problem | Recommendation |
|---|---|---|---|---|---|
| U1 | High | Analyze | `Hero.jsx` (240 px logo + "Turn Comments into Insights INSTANTLY!") above `Demo.jsx` | The marketing hero pushes the actual tool down: the **Analyze button sits at y ≈ 1075 px, below the fold**. This is an internal tool used repeatedly | Remove or compact the hero (the logo is already in the navbar). Put the upload card first |
| U2 | High | Account | Session management + "Sign out all devices" exist only in Dashboard (`Dashboard.jsx:421,480`), which basic users can't open | Basic users can't see or revoke their sessions. Personal settings are split between Profile and Dashboard | Move **Sessions** and **My activity** into Profile ("Security" section). Dashboard = Analytics + admin tabs |
| U3 | Medium | Dashboard | Overview tab (`Dashboard.jsx:421`): 👋 card + "Quick stats" duplicate the Profile account info and the Sessions tab | Low-value landing tab | Remove Overview; default to Analytics (or Team for admins) |
| U4 | Medium | History | History lives in browser `localStorage` (`HistoryComponent.jsx:49`); URL-extraction result files are deleted after the 24 h cache TTL (`cache_service.py` `_cleanup_entry_files`) | History is per-device and its download links silently 404 after a day for URL jobs | Short term: label it "on this device" and handle 404 gracefully. Better: a server-side "My results" list from the `tasks` table (data already exists) |
| U5 | Medium | Analyze | `Demo.jsx`: Analyze is disabled until a project is chosen, with no hint why; "Select project*" is the only clue | Users click a dead button | Helper text under the button ("Choose a project to continue"), or preselect when there is only one project |
| U6 | Medium | Login | "Forgot password?" link commented out (`Login.jsx:239`); `/forgot-password` and `/reset-password` are reachable only by URL | Users who forget their password have no self-service path | Re-enable after fixing E10, or remove the pages until then (**your call**) |
| U7 | Medium | Results | Results replace the form inside the same card; the pie chart has a fixed 400 px width; the stat tiles use `<h3>` for numbers | Weak hierarchy; the chart overflows on small phones | Responsive chart; tiles as a `<dl>` |
| U8 | Low | Branding | Dashboard header shows a letter "O" (`Dashboard.jsx` header), analytics title "🏺 Omnicat Usage Analytics", navbar "OMNICAT", logos alt-named "IN2_logo" before the fix | Inconsistent identity | Use the logo + "OmniCat" consistently; remove the emoji titles |
| U9 | Low | Analytics | Analytics shows a "🏺 Omnicat Usage Analytics" title directly under the "Analytics" tab header; Export/Refresh buttons are duplicated for mobile and desktop (`EnhancedDashboard.jsx:151,157,176,182`) | Duplicate titles | Keep one title; one responsive button row |
| U10 | Low | Info | The "Need help formatting your file? See an example sheet" link and the product description sit at the bottom, after the tool | Help is found after the user needed it | Move the sample-sheet link into the upload drop zone |
| U11 | Low | Errors | `alert()` / `window.confirm()` in History and Graphs downloads (`HistoryComponent.jsx`, `Graphs.jsx`) vs styled modals in Dashboard | Inconsistent, not styled | Reuse `Modal` / inline messages |

---

## 3. Proposed removals and merges

**⚠ = used by a route, API or flow: needs your confirmation.** The rest is unreferenced (verified by grep across `backend/` and `frontend/src`).

### Backend endpoints (none called by the frontend; verified by route ↔ source scan)

| Item | Evidence | Proposal |
|---|---|---|
| ⚠ `POST /api/upload/process_sync/{client_id}` | `upload.py:273`; returns "deprecated" | Remove |
| ⚠ `GET /api/upload/list/{client_id}`, `DELETE /api/upload/delete_file/...` | `upload.py:301,332` | Remove, unless a script or admin uses them (tell me) |
| ⚠ `POST /api/extraction/extract_url_cached/{client_id}` | Called internally by `/api/process_url`; also routable directly | Keep the function, drop the route decorator (one public entry point) |
| ⚠ `/api/extraction/{quick_status, batch_status, validate_url, cached_urls, extraction_stats, health}` | `extraction.py` | Remove `quick_status`/`batch_status` (duplicate `/api/tasks/task_status`) and `validate_url`. Keep `cached_urls` + `extraction_stats` only if admins use them via curl |
| ⚠ `/api/tasks/client/{client_id}`, `/api/tasks/health` | `tasks.py` | Remove (`/tasks/me/active` covers the UI) |
| ⚠ `/api/analytics/{simple-stats-range, presets, time-series, health, clear-data}` | `enhanced_analytics.py` | Remove `simple-stats-range`, `presets`, `time-series` (duplicates of `simple-stats`). Keep `clear-data` (admin) only if wanted |
| ⚠ `/api/info`, `/api/health`, `/api/upload/health`, `/test` | see E6 | Remove; keep `/health` (Docker healthcheck) |
| ⚠ `POST /api/admin/users`, `POST /api/admin/users/{id}/logout-all` | `admin.py`; no UI button | Keep as API for operators, or remove (users are created via invites) |
| ⚠ Backend SPA serving: `/`, `/config.js`, `/assets` mount, Jinja templates | `main.py:232-248, 497-518` | The backend image has no frontend build (nginx serves the SPA), so this path is dead in Docker. Remove |

### Backend code and files (unreferenced)
- Functions: `analyze_metadata_quality`, `check_dashboard_access`, `cleanup_resources`, `cleanup_temp_files`, `clear_all_tasks`, `compress_file`, `create_excel_with_charts`, `create_unique_filename`, `detect_platform`, `export_tasks_json`, `get_all_tasks`, `get_file_info`, `get_file_preview`, `get_processing_stats`, `get_project_stats`, `get_running_tasks`, `read_and_clean_excel` (non-enhanced), `reprocess_file`; `api/dependencies.py` `get_export_service`, `get_gemini_service`, `get_cache_service` (and the unused `get_task_manager` import in `upload.py:29`); `utils/dependencies.py` `require_role`/`require_permission` (unused factories); stale `ROUTE_SUMMARY` (`api/routes/__init__.py`).
- `processing.py:330-331` builds unused HTML `sentiment_table`/`category_table` strings into `result_data`.
- Files: `backend/create_tables.py` (superseded by `cli.py init`), `backend/BACKEND_ANALYSIS.md` and `docs/superpowers/*` (historical; move to `docs/archive/` or delete), `/app/analytics` dir in `Dockerfile:26`.

### Frontend
| Item | Evidence | Proposal |
|---|---|---|
| Unused deps: `@chakra-ui/react`, `framer-motion`, `@react-oauth/google`, `js-cookie`, `jwt-decode`, `react-medium-image-zoom`, `web-vitals` | 0 imports in `src` | Remove |
| `@material-tailwind/react` | Only an unused `Progress` import (`Demo.jsx:3`) | Remove |
| `@mui/x-charts` (+ `@emotion/*`) | One pie chart (`Graphs.jsx`); recharts already used | Merge onto recharts, remove MUI + emotion |
| Two lockfiles | `package-lock.json` + `pnpm-lock.yaml` (CI uses npm) | Remove `pnpm-lock.yaml` |
| Dead imports in `Demo.jsx` | `BsUpload`, `uuidv4`, `HistoryModal`, `HistoryButton`, `showHistoryModal` state | Remove |
| `HistoryButton` export | Never rendered | Remove |
| `ProtectedRoute` calls `authService.logout()` during render (`ProtectedRoute.jsx:12`) | Side effect in render; fires a request on every unauthenticated render | Clear local state only |
| ⚠ Dashboard **Overview** tab | U3 | Remove (merge into Profile) |
| ⚠ Dashboard **Sessions** + **My activity** | U2 | Move to Profile |
| ⚠ Hero section | U1 | Remove or compact |
| ⚠ Forgot / reset password pages | U6 | Re-enable the link (after E10) **or** remove |
| ⚠ Analytics "Export JSON" button | `EnhancedDashboard.jsx:84` | Keep if anyone uses it; otherwise remove |

### Repo / deploy
- `docker-compose.prod.yml` / `.staging.yml` (D9): fix or remove.
- `frontend/public/config.js` staging values (E11): placeholders.

---

## 4. Implementation plan

Each item is one focused commit. After each phase I run the backend tests, frontend lint, test and build, the core journeys in a browser, and the axe scan, and report before/after.

| Phase | # | Item | Refs | Effort |
|---|---|---|---|---|
| **0. You, now** | – | Rotate the leaked Google API key; check the server firewall for the DB port | E1, E2 | – |
| **1. Security** | 1.1 | Remove the Postgres host port from the prod overlay | E2 | S |
| | 1.2 | Upgrade vulnerable backend deps; swap python-jose → PyJWT | E3 | M |
| | 1.3 | `npm audit fix` (non-major); vitest major separately | E4 | S–M |
| | 1.4 | Remove `/api/info`, `/api/health`, `/test`; minimal `/health`; generic 500 messages | E6, D11 | S |
| | 1.5 | Move whitelist/dashboard emails to config | E5 | M |
| | 1.6 | Retention job + `SET NULL` on log FK (after your policy decision) | E8 | M |
| **2. Reliability / performance** | 2.1 | Non-blocking ExportComments + pandas calls (`asyncio.to_thread`) | D1 | M |
| | 2.2 | Mark interrupted tasks failed on startup | D2 | S |
| | 2.3 | Report unanalyzed comments instead of dropping them | D3 | M |
| | 2.4 | Keep task references; Gemini timeouts; upload timeout exemption | D4–D6 | S |
| | 2.5 | Add Alembic baseline + indexes + tz-aware `activity_logs.created_at` | D7, D8, D13 | M |
| | 2.6 | SQL aggregation for analytics (UTC buckets) | D10 | M |
| | 2.7 | Fix or remove compose overlays | D9 | S |
| | 2.8 | Route-level code splitting; compress images | D16, D17 | M |
| | 2.9 | Pipeline tests + CI lint/audit jobs | D15 | L |
| **3. Accessibility (2.2)** | 3.1 | Skip link, scroll-padding, per-route titles | A1–A3 | S |
| | 3.2 | Name the mobile filter toggle; chart text alternatives; table caption/scope | A4–A6 | M |
| | 3.3 | Responsive chart; 320 px / 400 % / target-size check; `dir="auto"` | A7–A9 | S |
| **4. UX/UI** | 4.1 | Compact hero; upload card first; sample-sheet link in the drop zone | U1, U10 | S |
| | 4.2 | Move Sessions + My activity to Profile; drop Overview | U2, U3 | M |
| | 4.3 | Analyze-button hint; project preselect | U5 | S |
| | 4.4 | History "on this device" label + 404 handling (or a server-side results list: L) | U4 | S / L |
| | 4.5 | Forgot-password decision (re-enable after E10, or remove) | U6, E10 | S |
| | 4.6 | Consistent branding; one analytics header; replace alert/confirm | U7–U9, U11 | M |
| **5. Cleanup** | 5.1 | Remove confirmed endpoints + dead backend code/files | §3 | M |
| | 5.2 | Remove unused frontend deps; merge charts onto recharts; drop the pnpm lockfile | §3 | M |
| | 5.3 | `CHANGES.md` (what changed, removed, manual steps) | – | S |

Rough total: about 4–6 working days, mostly in phases 2 and 4.

---

## 5. Decisions needed before Phase 2

1. **Branch:** this session is configured to work on `dev`. Your plan asks for a new branch. Should I create e.g. `audit-fixes` from `dev`, or keep working on `dev`?
2. **Removals marked ⚠ in §3:** approve all, or tell me which to keep (especially the operator-style endpoints and the "Export JSON" button).
3. **Retention policy (E8):** how long to keep activity logs, task results and uploaded files?
4. **Migrations (D7):** Alembic (recommended) or idempotent SQL steps in `bootstrap.py`?
5. **Forgot password (U6/E10):** fix the email sender and re-enable it, or remove the pages?
6. **Domain self-signup (E5):** should any `@in2-comms.com` Google account be able to create itself as `basic_user`?
