# Changes from the audit

This covers the work done on `dev` after [AUDIT_REPORT.md](AUDIT_REPORT.md) (commit `c618d4a`). IDs (E1, D3, A2, U5 …) refer to that report. Each fix is its own commit.

## Do these by hand

1. **Rotate the Google API key** that was committed to `README.md` in `570a090` (E1). It is still in git history. Rotating it is the fix; purging history is optional.
2. **Check the database password** from the `README.md` history (`570a090`) is not reused anywhere (E9).
3. **Check the server firewall.** The old `docker-compose.prod.yml` published Postgres on a host port (E2). Make sure nothing still exposes it.
4. **Remove the `HOST_*_PORT` variables** from server `.env` files. They are no longer read.
5. **CI needs Node 22** (vitest 5 requires Node ≥ 22.12). `.gitlab-ci.yml` and `frontend/Dockerfile` are already updated.
6. **Migrations run on their own.** The backend runs `alembic upgrade head` at startup under a Postgres advisory lock. The first revision only creates tables that are missing, so existing databases are safe. To run them by hand: `cd backend && alembic upgrade head`.
7. **Remove `FIRST_ADMIN_*`** from the environment after the first admin exists.
8. **Set `DATA_ENCRYPTION_KEY` before deploying.** Without it, docker compose and the backend both refuse to start. Generate it with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   - Store it in your secret store, **separately from the backups**. If it is lost, the encrypted data cannot be recovered.
   - **To rotate the key:**
     1. Set `new,old`.
     2. Restart.
     3. Stop the app (`docker compose stop omnicat-staging`), then run `docker compose run --rm omnicat-staging python -m cli rotate-key`, which re-encrypts every row and file with the new key. Start the app again. The command is safe to re-run.
     4. Only after that, remove the old key. Without step 3, 2FA secrets and activity logs, which are kept 365 days, become unreadable.
9. **First deploy of this version. These steps are one-way, so follow them in order:**
   1. **Back up the database and the uploads folder** (`/data/omnicat-staging/uploads`). This release:
      - encrypts existing rows and files;
      - deletes data already past retention (tasks over 30 days, activity logs over 365 days);
      - anonymises old usage records.

      Migration 0003 cannot be downgraded, and the old image cannot read encrypted data. Rolling back means restoring **both** backups, which loses anything written after the deploy.
   2. **Check the table sizes:** `SELECT pg_size_pretty(pg_total_relation_size('tasks')), pg_size_pretty(pg_total_relation_size('activity_logs'));`. If either is more than a few hundred MB, run the migration once by hand before starting the service: `docker compose run --rm omnicat-staging alembic upgrade head`. Otherwise the 120 s worker timeout can interrupt it at startup. It deletes expired rows first and then works in batches.
   3. **Make the uploads folder writable by the app user:** `chown -R 1001:1001 /data/omnicat-staging/uploads`. The one-time encryption of existing files needs it.
   4. **Watch the startup logs for migration 0005.** If it says "unique index skipped", some accounts differ only by letter case (e.g. `Ali@` and `ali@`). Merge or delete them, then run `alembic downgrade 0004 && alembic upgrade head`.
10. **Reverse proxy on the host.** The nginx in front of the containers isn't in this repo. Set:
    - `client_max_body_size 55m;` (uploads can be up to 50 MB);
    - `proxy_read_timeout 300s;` for `/api/analysis/` (chat and Apply can make several AI calls) and `/api/upload/`;
    - `proxy_buffering off;` for `/api/progress/` (live progress).

    If Cloudflare is in front, its 100 s limit also applies.

## Privacy (GDPR)

Personal data is encrypted at rest. Only the user can see their own content. Retention runs automatically, and users can download or erase their data themselves.

**Encryption.** Encryption uses Fernet (AES with HMAC) with `DATA_ENCRYPTION_KEY`, which is kept outside the database (`utils/crypto.py`).
- **Files:** uploads, extracted comments and results are encrypted on disk. They are decrypted only in memory, for processing and download.
- **Database:** task results and AI summaries, task details, cached URLs, IPs, user agents, devices, log details and the 2FA secret are encrypted.
- **Stays readable, because the app must search on it:** email, name, roles, project names, action names and timestamps.

**What admins see.**
- Admins see who did what and when (the security log), usage counts per project, and each user's sessions without device or IP, which they can still revoke.
- Admins never see files, results, summaries, URLs, file names, IPs or devices, including in the CSV export.
- Users see all of their own data on Profile.

**Retention** (`services/privacy.py`, runs at startup and then hourly):

| Data | Kept for |
|---|---|
| Results, result files, analyses, URL cache | 30 days |
| Uploaded input files | deleted as soon as processing ends |
| Usage records | 30 days with identity, then anonymised (counts stay for analytics) |
| Activity logs | 365 days |
| Expired sessions; invitations expired over 30 days ago | deleted |

**User rights** (Profile → "Your data"):
- **Download my data:** a ZIP with profile, sessions, activity, analyses and decrypted files (access and portability).
- **Delete** in History removes that result from the server.
- **Delete all my data:** erases files, analyses and activity, and keeps the account.
- **Delete my account:** erases everything; usage counts stay anonymised.
- Both erasures ask the user to type their email. Deleting a user as an admin also erases their files.

**Other fixes in this round:**
- The URL cache was shared between users. One user could be served another user's results, and a missing file was copied from another user's folder. The cache is now per user. Old cache entries were cleared; they were 24-hour copies.
- Task IDs, stored file names and application log lines no longer contain emails, post URLs or file paths.
- Removed admin "set password" (`POST /api/admin/users/{id}/set-password`). It let an admin sign in as any user. A user who forgets their password needs the forgot-password email (U6), or an admin can delete the account and send a new invitation.

**Not covered by code (your side):**
- **Processors:** comment text goes to Google (Gemini) and post URLs go to ExportComments. Sign their data processing agreements and list them in your privacy notice. On Google's side, use a paid Gemini API tier, whose terms exclude training on your data.
- **Privacy notice and records of processing:** state the purpose, the legal basis and the retention periods above.
- **Server and backup logs:** the API has the user's email in some URL paths (for example `/api/upload/process/{email}`), so access logs (nginx, gunicorn) contain it. Keep those logs, and database and file backups, for no longer than the periods above.

## AI analysis and chat

**Classification.**
- Comments go to Gemini in batches of up to 25 instead of one call each. The fixed instructions are sent once as a system instruction.
- Answers come back as JSON that must match a schema, so the category can only be one from the taxonomy.
- Identical comments are analysed once. Missing or invalid answers are retried up to three times, then reported as unanalysed.
- The sentiment label comes from the score in code, so one rule applies everywhere.
- This means roughly 10–25× fewer calls (`services/gemini_service.py`).

**Summaries.**
- One call now produces an **overall summary**, which is new, plus positive, neutral and negative summaries.
- The call sees the English translations grouped by sentiment and tagged by category, the counts, the top categories and the post context.
- Large posts are sampled evenly within about 30k tokens. Before, it read only the first 25,000 characters of raw text.
- The overall summary appears above the three cards and in the Excel report.

**Chat ("Ask about these results", under every result).** The code is in `services/chat.py`, `routers/analysis.py` and `AnalysisChat.jsx`.
- **What Gemini sees:** an overview (counts, top categories, summaries, post context), plus the whole dataset when it fits (about 50k tokens). Otherwise it uses a `search_comments` tool.
- **Short-term memory:** the last 20 messages of that result's conversation.
- **Refine summaries:** the user asks for a different focus, tone or length. The assistant prepares new summaries, which replace the old ones only when the user presses **Apply**.
- **Fix labels:** the user points out mislabelled comments. The assistant proposes specific changes (each shown as text, old label → new label, at most 200), which apply only on **Apply**.
  - Applying rebuilds the report, counts and charts.
  - A changed sentiment gets a matching score (±0.5 or 0).
  - The summaries are regenerated.
- **Safety:**
  - Comment text is treated as data, not instructions.
  - Tools run in an explicit loop of at most 5 rounds.
  - The assistant can only read the user's own result and can't change anything without Apply.
  - Chat is limited to 20 messages per minute.
- **Privacy:**
  - Chats are encrypted.
  - They are deleted with the result, after 30 days, or with the account.
  - They are included in "Download my data".
- Long-term memory, such as a saved brief per project, is not built. It's optional and can be added later.

**Check after deploying:** I tested all of this with Gemini replaced by a scripted fake, because no real API key is available here. Run one real analysis and a short chat on staging to confirm that the batching, the JSON schema and tool calling work with your Gemini models (`gemini-3.1-flash-lite`, falling back to `gemini-2.5-flash`). Migration 0004 (`chat_messages`) runs automatically.

## What changed

### Security
- Removed the compose overlays that published Postgres on the host (E2, D9).
- Upgraded vulnerable backend packages (FastAPI 0.143, python-multipart, aiohttp, requests, python-dotenv). Replaced python-jose with PyJWT (E3).
  - `setuptools` stays below 81 because the ExportComments SDK still needs `pkg_resources`. That one advisory is ignored in CI.
- Fixed the frontend `npm audit` findings, including the vitest 5 upgrade (E4). `npm audit` now reports 0.
- Removed `/test`, `/api/info` and `/api/health`. `/health` now returns only `{"status": "ok"}`. Server errors return a generic message and the details go to the log (E6, D11).
- Endpoints with rate limits returned 500 on success; fixed (bug present since `941aff1`).
- `frontend/public/config.js` no longer holds staging values (E11).

### Reliability and performance
- ExportComments calls and pandas Excel reads/writes no longer block the event loop (D1).
- Jobs interrupted by a restart are marked failed with a clear message, at startup and every 5 minutes, instead of hanging (D2).
- Comments the AI could not analyze are counted and shown to the user instead of silently dropped (D3).
- Background jobs keep a reference so they can't be garbage-collected. Gemini calls have a timeout. Uploads are exempt from the 120 s request timeout (D4–D6).
- Processed result filenames are now unique, so a new result can't overwrite an older one.
- Added Alembic migrations, indexes on `activity_logs(user_id, created_at)` and `refresh_tokens(user_id)`, and a timezone-aware `activity_logs.created_at` (D7, D8, D13).
- Analytics aggregates in SQL and uses UTC days (D10).
- Frontend bundle: Dashboard, Profile and charts load on demand, and images are WebP (D16, D17).
  - Main JS 1.68 MB → 366 KB (118 KB gzip).
  - Images 914 KB → 19 KB.
- Added tests for the processing pipeline, ExportComments, migrations and analytics, plus a CI dependency-audit job (D15). ESLint now runs in CI.

### Accessibility (WCAG 2.2 AA)
- Skip link, a title for each page, and focus no longer hidden under the sticky header (A1–A3).
- Charts have text alternatives. The usage table has a caption and header scopes (A4–A6).
- The results chart is responsive (checked at 320 px). User-entered text uses `dir="auto"` for Arabic (A7, A9).
- All dialogs share one accessible `Modal`: focus moves in, is trapped, Escape closes it, and focus returns.
- axe-core: 0 violations on all 12 views at 1280 px and 375 px.

### UX
- The upload tool is first on the page. The header is compact and the example sheet link sits at the upload box (U1, U10).
- Profile has "Signed-in devices" and "Recent account activity" for every user. Dashboard is now Analytics plus the admin tabs (U2, U3).
- The Analyze button says what is missing, and the only project is preselected (U5).
- History now comes from the server (`GET /api/analysis`), not the browser, so it is the same on every device and its count stays current. **Open** shows a past result again, with its chat, at `/app?result=<file>`. Downloads of expired results show a clear message (U4). The old browser-stored history is removed when the user next opens the app.
- Consistent OmniCat branding, one analytics toolbar, and inline errors instead of `alert()`/`confirm()` (U7–U9, U11).

## What was removed

All approved in the audit ("approve all removals").

**API endpoints.** The frontend called none of these. Each now returns 404, and a test checks that.
- `/test`, `/api/info`, `/api/health`
- `/api/upload/process_sync/{id}`, `/api/upload/list/{id}`, `/api/upload/delete_file/{id}/{file}`, `/api/upload/health`
- `/api/extraction/*`: `extract_url_cached` (still used internally by `/api/process_url`), `quick_status`, `batch_status`, `validate_url`, `cached_urls`, `extraction_stats`, `health`
- `/api/tasks/client/{id}`, `/api/tasks/health`
- `/api/analytics/simple-stats-range`, `presets`, `time-series`, `clear-data`, `health`
- `POST /api/admin/users` (users join by invitation), `POST /api/admin/users/{id}/logout-all`
- Backend SPA serving: `/`, `/config.js` and `/assets`. The frontend container serves these. Jinja2 was removed with them.

**Backend code and files:**
- Unused functions in `file_utils`, `processing`, `task_manager`, `cache_service`, `simple_analytics`, `whitelist` and the dependency modules.
- The unescaped HTML `sentiment_table`/`category_table` in task results.
- `create_tables.py`, `BACKEND_ANALYSIS.md` and `docs/superpowers/`.

**Frontend:**
- Removed the Dashboard Overview and Sessions tabs (sessions moved to Profile), the analytics "Export JSON" button and the large hero.
- Removed 11 unused packages: Chakra, Emotion, MUI x-charts, Material Tailwind, framer-motion, `@react-oauth/google`, js-cookie, jwt-decode, react-medium-image-zoom and web-vitals.
- Removed `pnpm-lock.yaml`, unused images and the `HistoryButton` export.
- `ProtectedRoute` no longer calls logout while rendering.

## Verification

- Backend: 289 tests pass, including the results list, batching, summaries, chat, proposals, relabelling, migrations against SQLite, checks for the removed routes, encryption, admin views, retention and every user right.
- Migration 0003 checked on Postgres, both on a fresh database and on a copy holding real data. The values end up encrypted and read back correctly.
- Frontend: 11 tests pass. `npm run build` passes.
- ESLint: 0 errors, down from 78 problems. The 7 remaining warnings are deliberate run-once effects.
- Core journeys on the real stack (Postgres + backend + Vite): 15/15 pass. axe reports 0 violations, including the delete-account dialog.
  - Sign in, including a wrong password.
  - Create a project and an invitation, then register through the invitation.
  - Upload and see the failure message.
  - Profile devices, activity and password change.
  - Logout and the protected route.
  - Download my data as a ZIP, then delete the account; the deleted account can no longer sign in.
- AI journey with Gemini faked: 17/17 pass, using the default relative `API_URL`. It covers downloading from the results page and deleting the open result, as well as analysis to results with the overall summary, a chat answer, applying new summaries, applying a label fix (counts update), the History count updating, History listing the result, Open showing it again with its chat, and the stored conversation. axe reports 0 violations on the results, chat and History.

**Final review.** Two independent reviews of every change since the audit found 13 issues, all now fixed and covered by tests:
- Applying a chat change could drop columns when the upload had a blank header.
- An edited result outlived the 30-day retention.
- Concurrent applies could overwrite each other.
- The results-page download failed when `API_URL` is relative (local dev).
- Switching or deleting results could show the wrong one or a stale chat.
- Retention could abort when several workers ran it at once.
- Users with a `+` in their email (`ali+work@…`) could not upload, download, export or delete their data. This predates the audit.
- Re-processed cached links were counted under the "default" project. This also predates the audit.
- Smaller fixes: blocking file work moved off the request loop, one shared Gemini rate limiter, and the cached-link timer is stopped.

**Second review: attacker, deploy-day and real-world-data lenses.** All findings are fixed and tested.

Security:
- **Accounts differing only by letter case** (`Basic@` vs `basic@`) could be created and could reach each other's files, exports and erasure. Emails are now one account whatever the case: matched case-insensitively, stored in lower case, with a unique index (migration 0005). File paths and data matching always use the signed-in account, never the URL.
- **Unusual emails:** `o'brien@…` accounts can now export and erase their data.
- **Export** no longer stalls the server and is limited to 5 an hour.
- **Chat:** malformed tool calls can't crash it, apply-lock entries no longer pile up, and Apply is rate-limited.
- **Logs and messages:** logs no longer contain post context, recipient emails or URLs, and users see a generic message instead of internal error text.

Data:
- **Links:** text starting `http…` or `mailto:` is no longer turned into live links or blanked.
- **"NA" and "None" values:** "NA", "None", "N/A" and leading zeros ("007") are kept as written, so such comments are no longer dropped.
- **Clashing column names:** input columns named like output columns are kept as "<name> (original)".
- **Link exports:** when two source columns map to the same name, the second no longer overwrites the first.
- **Invalid AI scores:** a NaN score is rejected instead of becoming "very positive".
- **Summary sampling:** large groups of long comments are sampled evenly instead of only their first 20%.

Deploy:
- **Migration 0003:** deletes expired rows first, then encrypts in batches. Memory use is flat and it is much faster.
- **Retention failures:** the housekeeping loop no longer spins thousands of times a second when retention fails.
- **Legacy-file encryption:** the scan runs once, tolerates missing files and keeps file ages.
- **Key rotation:** `cli rotate-key` added.
- **Timeouts:** chat and Apply are exempt from the 120 s request timeout.
- **Open tabs:** they survive a deploy.
- **docker-compose:** requires the key and caps log sizes.
- **CI:** builds images only when every check passes.

## Still open (needs your decision)

- **U6 / E10 forgot password:** the Resend sender `onboarding@resend.dev` only delivers to the account owner. Either verify a sending domain and re-enable the "Forgot password?" link, or remove the pages.
- **E5 sign-up:** should any `@in2-comms.com` Google account be able to create itself as `basic_user`? Should the hard-coded staff emails in `utils/whitelist.py` move to configuration?

## Not done (low priority)

- E7: rate limits are counted per worker in memory. Shared limits would need Redis.
- D12: N+1 queries in the admin user list and the activity log responses.
- D14: startup messages use `print` instead of the logger.
- A10: manual screen reader pass (VoiceOver / NVDA).
