# Operations & Handover

Everything needed to run, refresh and debug the platform in production.
Architecture is in [ARCHITECTURE.md](ARCHITECTURE.md); first-time deployment is
in [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 1. What runs where

| Component | Host | Connects as | Deploys when |
|---|---|---|---|
| **API** (FastAPI) | Render — `nhs-capacity-api.onrender.com` | `nhs_reader` (read-only) | push to `main` (`autoDeploy: true`) |
| **Frontend** (React/Vite) | Vercel (`frontend/vercel.json`) | — calls the API | push to `main` |
| **Database** | Supabase, project `dtxavwlqmefuhyphjikk`, eu-west-1 | — | — |
| **Scheduled refresh** | GitHub Actions `refresh.yml` | `postgres` (owner) | every 12h, or manually |
| **NHS real-data ingestion** | **your laptop** — see §3 | `postgres` (owner) | monthly, manually |

The API is on Render's free plan and sleeps when idle. A first request after
that takes **~150 seconds**. That is a cold start, not an outage — don't
diagnose it as one.

### Database roles

| Role | Used by | Can write? |
|---|---|---|
| `postgres` | refresh workflow, `ingest_nhs_real.py`, `harden()` | yes — owns every table |
| `nhs_reader` | the **API only** | no — `SELECT` only, via RLS policies |

Anything that writes must stay on `postgres`. Only the API uses `nhs_reader`,
so a bug in the NL→SQL layer cannot mutate the warehouse: the database itself
refuses it.

---

## 2. Automatic: the 12-hourly refresh

`.github/workflows/refresh.yml` rebuilds the DuckDB gold warehouse, re-seeds the
A&E digital twin, publishes everything to Supabase and re-applies the security
posture. No action needed unless it fails.

Check it:

```powershell
gh run list --workflow=refresh.yml --limit 5
```

It does **not** collect the real NHS England data — see below for why.

---

## 3. Monthly: refresh the real NHS England data

**When:** NHS England publishes on the **second Thursday of each month**, around
09:30 UK time, covering the previous month. Run this any time after that.

**Why it is manual:** NHS England's WAF answers datacentre IP ranges — GitHub
Actions runners included — with `202 Accepted` and an empty body. Because 202 is
a success status it slips past normal error handling, so the scheduled refresh
would report success having ingested nothing. The code now detects and names
this (`NhsEnglandUnavailable`), and the same request succeeds from an ordinary
home or office connection.

**Run it from your machine:**

```powershell
python scripts/ingest_nhs_real.py
```

Takes a couple of minutes — the RTT extract is ~82MB compressed, ~330k rows.
Expect output like:

```
  published 547 rows to nhs_ae_monthly (3 month(s))
  published 3,524 rows to nhs_rtt_monthly (1 month(s))
```

**Then re-apply the security posture.** The ingestion recreates those two
tables, and a recreated table loses its RLS setting and policies:

```powershell
python -c "import importlib.util; s=importlib.util.spec_from_file_location('p','scripts/publish_to_postgres.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.harden()"
```

You can skip that if you don't mind waiting — the next scheduled refresh runs
`harden()` anyway, within 12 hours.

**Then sanity-check the figures** against the NHS England press release. They
should match exactly; if they don't, see §6.

```powershell
Invoke-RestMethod https://nhs-capacity-api.onrender.com/api/nhs/rtt | Select-Object -ExpandProperty national
```

---

## 4. Credentials

| Secret | Lives in | Role |
|---|---|---|
| `DATABASE_URL` | GitHub repo secret | `postgres` |
| `DATABASE_URL` (or `DB_*`) | Render env vars | `nhs_reader` |
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` | local `.env` (gitignored) | `postgres` |
| `OPENROUTER_API_KEY` | Render env var | — |

**Supabase pooler gotcha.** The session pooler identifies the project from the
username, so it must be `<role>.dtxavwlqmefuhyphjikk`, never a bare role name.
A bare name is rejected as `password authentication failed for user "postgres"`
— and note it says `postgres` **even when your username is correct**, because
the pooler reports the underlying role. Do not chase the username on that error
alone; check the preflight output, which prints the username it used.

**Password encoding.** Prefer `DB_HOST` / `DB_USER` / `DB_PASSWORD` over a full
`DATABASE_URL`: the code percent-encodes the password for you
(`resolve_database_url` in `src/config.py`). Hand-encoding a URI is what broke
the refresh for 72 days — a stray `/`, `@`, `:`, `%`, `#` or `?` produces a
"wrong password" error with a perfectly correct password.

---

## 5. Security model

All 14 public tables: **RLS enabled, no anon policies, no grants to `anon` or
`authenticated`.** Nothing in this project uses the Supabase client libraries —
the SPA talks only to the API — so the PostgREST roles need no access at all,
and "no policy" is a stronger guarantee than a read policy nobody exercises.

Supabase's linter reports `rls_enabled_no_policy` at INFO level on these tables
**forever**. That finding is the intended state. Do not "fix" it by adding an
`anon` SELECT policy unless you actually add a Supabase-client feature.

This posture is **re-applied automatically** by `harden()` at the end of every
publish. It has to be: publishing recreates the optional tables, and a recreated
table silently loses its RLS setting — four tables lost protection within
minutes the first time it was set by hand. **Never re-fix this with one-off
SQL; change `harden()` in `scripts/publish_to_postgres.py`.**

To re-verify the read-only role end to end (reads every table, refuses writes):

```powershell
# add READER_DB_USER=nhs_reader.dtxavwlqmefuhyphjikk and READER_DB_PASSWORD to .env
python scripts/check_reader_role.py
```

Verify which role the API is actually using — in the Supabase SQL editor:

```sql
SELECT usename, application_name, state, backend_start
FROM pg_stat_activity WHERE datname = 'postgres' AND usename = 'nhs_reader';
```

A connection with `application_name = 'Supavisor'` and `SELECT 1` as its last
query is the API's SQLAlchemy pool.

---

## 6. Runbook

### The dashboards are empty but the API returns 200

Almost certainly RLS. `nhs_reader` does not own the tables, so a missing read
policy returns **zero rows, not an error**. Run `scripts/check_reader_role.py`.
If tables come back empty, run `harden()`.

### The refresh workflow fails on the database

Read the preflight line first — it prints the username it used, which
distinguishes a bad username from a bad password. Then see §4. The workflow can
also be disabled by GitHub after a long quiet period:

```powershell
gh workflow list --all          # look for "disabled_manually" or "disabled_inactivity"
gh workflow enable "Refresh data"
```

### The refresh is green but the NHS tables are stale

Expected — see §3. The refresh cannot reach NHS England. Check the log for
`nhs_england.blocked`, then run the ingestion locally.

### The real NHS figures look about 2x too big

The published files embed regional and national `TOTAL` rows among the provider
rows. Summing as-published double-counts everything, and ratios like four-hour
performance still look perfectly correct, so only absolute numbers give it away.
`_drop_aggregate_rows` handles this; if NHS England renames those markers it
will need updating.

### The RTT waiting list looks ~3x too small

Wrong part type. The waiting list is `Part_2` ("Incomplete Pathways").
`Part_2A` is the narrower "with DTA" subset. See `RTT_INCOMPLETE`.

### An NHS England download 404s

The URLs carry a rotating token (`...-97ylx5.zip`) and are **discovered by
scraping**, never constructed. If discovery breaks, NHS England has changed
their page markup — update `AE_CSV_LINK` / `RTT_ZIP_LINK` in
`src/ingestion/nhs_england.py`.

### The API is slow or times out on first request

Render free-plan cold start, ~150s. Not an outage.

### `curl -s ...` prompts for `Uri:` in PowerShell

`curl` is an alias for `Invoke-WebRequest`. Use `Invoke-RestMethod`, or
`curl.exe` to get the real binary.

---

## 7. Health check

```powershell
Invoke-RestMethod https://nhs-capacity-api.onrender.com/api/health
Invoke-RestMethod https://nhs-capacity-api.onrender.com/api/overview/kpis
Invoke-RestMethod "https://nhs-capacity-api.onrender.com/api/nhs/rtt?limit=3"
```

`/api/overview/kpis` reads **views**, which are owned by `postgres` and
therefore bypass RLS — it will return data even if every policy is broken. To
test the security path you must hit a base-table endpoint: `/api/nhs/rtt`,
`/api/ops/state`, or `POST /api/ask`.

---

## 8. Known gaps

- **`API_KEY` is unset on Render**, so `/api/*` is open to anyone with the URL.
  Set it to require an `X-API-Key` header. Note that a key baked into a public
  SPA is obfuscation, not secrecy — real public auth needs user OAuth/JWT.
- **The database password has been shared in chat transcripts.** Rotate it when
  convenient, updating the GitHub secret, Render, and local `.env` together.
- **Daily and minute-level figures are modelled.** NHS England publishes
  monthly, so the daily fact table and the A&E digital twin are necessarily
  simulated on top of the real trust roster. The Evidence & Validation page
  states this per source; keep it accurate if sources change.
