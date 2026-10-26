# TradeIQ infra operations: Postgres, scheduler keepalive, auth

Live app: https://optionstrade-1raj.onrender.com (service `tradeiq`, free plan).
Branch: `fix-infra-postgres-scheduler-auth`. This doc is the operator guide
for the three Priority 4 items. Nothing here changes data or deletes anything.

## 1. Postgres: configured, verified live

Verdict: **DATABASE_URL is set on Render and points at a persistent
Postgres. Do not remove it, and do not "fix" the database setup.**

Evidence, checked live on Oct 26, 2026 at about 3:30 PM ET:

- `GET /api/challenge` returns the Challenge account created
  `2026-10-23T23:34:49` (start date Oct 23, $1,000) and snapshot id 1
  taken `2026-10-24T00:06:57`. That data was written Oct 23-24 and is
  still present Oct 26.
- Master `1009156` was deployed Oct 24 and confirmed live Oct 24, 9:40 PM
  ET, which is after the Challenge data was written.
- Render's own docs say a free web service has an ephemeral filesystem:
  local files (including a SQLite file in `/tmp`) are lost on every
  redeploy, restart, or spin-down. A `/tmp/trading.db` file could not
  have survived the Oct 24 deploy, so the surviving Challenge data proves
  the app is writing to Postgres, not to the SQLite fallback.
- Code agrees: `backend/database.py` uses `DATABASE_URL` when present and
  falls back to SQLite at `DB_PATH` (`/tmp/trading.db` in `render.yaml`)
  only when it is absent.

Caveats, stated plainly:

- The Render dashboard itself was not inspected (no dashboard access in
  this task), so the provider behind the URL is not directly confirmed.
  `render.yaml` and `backend/database.py` both point at Neon
  (https://neon.tech), which is the likely provider. Confirm in the
  dashboard: Environment tab, `DATABASE_URL` value, host name.
- If the database turns out to be a free Render Postgres instead of
  Neon, note that free Render Postgres databases expire 30 days after
  creation. Check the creation date in the dashboard; if expiry is near,
  move the data to Neon before it lapses. Neon free tier has no such
  expiry.
- `render.yaml` now carries a comment recording this verification so a
  future edit does not accidentally drop the variable.

## 2. Scheduler: in-process APScheduler is not sufficient alone

Verdict: **the scheduler works when the instance is awake, but the free
plan spins the instance down, so an external pinger is required.**

How it works today: `backend/scheduler.py` runs APScheduler in-process
(`BackgroundScheduler`, America/New_York). Jobs include the 6:00 AM
discovery scan, 8:00 AM alert outcome job, 8:15 AM champion outcome job,
9:10 AM champions scan, 9:00/9:45/12:00/15:00/18:00 analysis runs,
5:15 PM Challenge snapshot, and 5:30 PM alert engine. Each job skips
non-trading days and has a misfire grace window (30 minutes for the
morning jobs), so a job that fires a few minutes late still runs.

Why that is not enough on the free plan:

- Render spins a free web service down after 15 minutes without inbound
  traffic, and spins it back up (about a minute) on the next request.
  A spun-down instance runs no code, so no 6:00 AM job can fire while
  the service is asleep. A job missed while the process is down is never
  retried on restart (default in-memory job store, no catch-up).
- Observed live Oct 26 at about 3:30 PM ET: `/api/status` showed every
  engine `idle` with `last_run: null`, and `/api/discovery` showed
  `status: idle, results: null, generated_at: null`. The options, wheel,
  and directional engines record their runs in `run_status`, and the
  discovery state lives only in process memory, so a process that had
  run the morning jobs would not look like this. This process started
  fresh mid-day, which means the service spun down and restarted during
  the day, and all in-memory run state reset with it. Do not use
  `/api/status` or `/api/discovery` as durable proof that a morning job
  ran; the database-backed records (Challenge snapshots, journal rows)
  are the durable evidence.
- The morning jobs did fire Oct 26 while the instance was awake, but
  nothing in the current setup guarantees the 6:00 AM job fires on a
  quiet morning. That is the gap this branch closes.

Fix in this branch (mergeable, no dashboard-only change):

- New public endpoint `GET /api/keepalive` (see `backend/main.py`). It
  returns `{"status": "ok", ...}` plus the scheduler state and the next
  run time of every job, so a pinger hit both keeps the instance awake
  and shows the schedule is intact.
- New endpoint `GET /api/scheduler` (auth applies) listing every job
  with its next run time, for a quick check that the morning jobs are
  still scheduled.
- No Render cron job was added to `render.yaml`, on purpose: Render cron
  jobs have no free plan (cheapest is Starter), so a blueprint cron job
  would either fail validation or cost money. The free path is an
  external pinger, documented below.

What Rohit still has to do (dashboard, about 5 minutes, after merge and deploy):

1. Create a free UptimeRobot account (uptimerobot.com), Add New Monitor,
   type HTTPS, friendly name `TradeIQ keepalive`, URL
   `https://optionstrade-1raj.onrender.com/api/keepalive`, monitoring
   interval 5 minutes. Optional: keyword monitoring for `"status":"ok"`.
   Alternative: cron-job.org, free, same URL, every 5 minutes.
2. Leave it running. A hit every 5 minutes means the service never
   reaches 15 idle minutes, so it stays awake and the morning jobs fire
   on time. A brief wake delay is covered by the 30-minute misfire grace
   windows.
3. Verify the next morning: `GET /api/scheduler` shows the 6:00 AM
   discovery job with a next run time, and after 6:00 AM the discovery
   results are present. If the pinger ever stops, the symptom is the
   morning jobs silently not running, which is why the keepalive
   endpoint returns the job list.

Cost note: a service kept awake 24/7 uses about 720 hours in a 30-day
month (744 in a 31-day month) against the 750 free instance hours per
workspace per month. That fits for this single service, with almost no
headroom. If other free services share the workspace and the allowance
runs out, Render suspends the free services until the next month; that
is the signal to pay $7/month for Starter, which also stops the
spin-down entirely.

Known gap, not built here: if the service restarts (deploy, crash) after
a morning job's time has passed, that day's job is skipped, pinger or
not, because there is no startup catch-up. A deploy before 6:00 AM is
safe; a deploy at, say, 7:00 AM loses that day's discovery scan. If that
matters, the follow-up is a startup catch-up that runs any morning job
whose time passed while the process was down.

## 3. Auth: simple login, off by default

Verdict: **no auth existed; this branch adds HTTP Basic auth (plus an
optional Bearer token), gated by env vars, with a safe default.**

How to enable (Render dashboard, after merge and deploy):

1. Environment tab, add `TRADEIQ_AUTH_USER` (a username) and
   `TRADEIQ_AUTH_PASSWORD` (a long password). Save; Render redeploys.
2. Open the app. The browser prompts once for the login, then remembers
   it; every same-origin request (including the React frontend's API
   calls) carries the credentials automatically. No frontend change was
   needed: the app calls its own origin, and fetch sends the browser's
   stored Basic credentials by default on same-origin requests.
3. Alternative for scripts: set `TRADEIQ_AUTH_TOKEN` instead (or as
   well) and call with `curl -H "Authorization: Bearer <token>" ...`.
   Either credential type works; both set is fine.

Behavior and safe default:

- When neither variable is set, auth is completely off and the app
  behaves exactly as before. Nothing in this branch locks Rohit out of
  his own app by default. The startup log prints a warning when auth is
  off, and the enabled state when it is on.
- When auth is on, every route requires it except `GET /api/health` and
  `GET /api/keepalive`, which stay public so the uptime pinger works
  without credentials and Render-style liveness checks keep working.
  Unauthenticated requests get HTTP 401 with a `WWW-Authenticate:
  Basic` header, which is what triggers the browser login prompt.
  `OPTIONS` preflight requests pass through so local development from
  `localhost:5173` keeps working.
- Setting only one of user/password leaves auth off and logs a warning;
  both are required.
- API keys (Anthropic, Polygon, Finnhub, FMP, Telegram) are untouched:
  they stay server-side environment variables and are never used as
  login credentials or exposed by the auth check.

Local test: put the two variables in `.env` (see `.env.example`) or
export them before starting uvicorn. `curl -s
http://localhost:8000/api/health` still returns `{"status":"ok"}` with
no credentials; `curl -s http://localhost:8000/api/options` returns 401
without credentials and the data with `-u user:password`.

## 4. Dashboard checklist for Rohit (after merge and deploy)

1. Environment tab: confirm `DATABASE_URL` is present. Note the host:
   Neon (expected) or Render Postgres (check the 30-day expiry if so).
2. Environment tab: set `TRADEIQ_AUTH_USER` and
   `TRADEIQ_AUTH_PASSWORD` (or `TRADEIQ_AUTH_TOKEN`). Save and let it
   redeploy, then confirm the browser prompts for the login.
3. UptimeRobot (free): add the 5-minute HTTPS monitor for
   `https://optionstrade-1raj.onrender.com/api/keepalive`.
4. Verify: `GET /api/keepalive` returns `status: ok` with a job list;
   `GET /api/scheduler` (after login) shows the morning jobs with next
   run times; the next morning, the 6:00 AM discovery results are
   present.
5. Nothing to do about Postgres: it is already configured and proven
   live. Do not change `DATABASE_URL` or `DB_PATH`.
