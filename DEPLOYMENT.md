# Deployment

Three tiers: **Frontend → Vercel**, **API → a container host (Render)**, **Database → Supabase (PostgreSQL)**.

```
 ┌─────────────┐   HTTPS    ┌──────────────────┐   psycopg2/SSL   ┌────────────────────┐
 │ React SPA   │──────────▶ │ FastAPI (Docker) │ ───────────────▶ │ Supabase Postgres  │
 │ Vercel CDN  │            │ Render web svc   │   pooler:5432    │ (eu-west-1)        │
 └─────────────┘            └──────────────────┘                  └────────────────────┘
```

---

## 0. Database — Supabase (done)

The medallion **gold** tables are published into Supabase by `scripts/publish_to_postgres.py`.

> **Supabase connection string.** Direct connections (`db.<ref>.supabase.co`) are **IPv6-only**.
> For IPv4 hosts (Render, most laptops) use the **session pooler**:
>
> ```
> postgresql+psycopg2://postgres.<project-ref>:<URL-ENCODED-PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
> ```
>
> URL-encode the password (`/` → `%2F`, `@` → `%40`). This project resolved to region
> **eu-west-1**. Exact URI: Supabase dashboard → **Connect → Session pooler**.

Re-publish after a pipeline run:

```bash
export DATABASE_URL='postgresql+psycopg2://postgres.<ref>:<enc-pwd>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require'
python scripts/run_pipeline.py        # rebuild the gold warehouse (DuckDB)
python scripts/publish_to_postgres.py # load it into Supabase
```

### Database access posture

All 12 public tables have **RLS enabled with no policies**, and the `anon` and
`authenticated` roles hold no grants. That is deliberate, not an oversight:

* Nothing in this project uses the Supabase client libraries. The React SPA
  talks only to the FastAPI backend, so the PostgREST roles need no access at
  all — and "no policies" is a stronger, simpler guarantee than a read policy
  nobody exercises.
* The API connects as `postgres`, which owns the tables, and table owners
  bypass RLS unless `FORCE ROW LEVEL SECURITY` is set. So the lockdown closes
  the anon-key surface without touching the application.

Supabase's linter reports `rls_enabled_no_policy` at INFO level for these
tables. That finding is expected here and should stay: it means the tables are
unreachable through the public API, which is the intent. Should you ever add a
Supabase-client feature, add a `SELECT`-only policy for `anon` at that point.

### Least-privilege role for the AI query path (recommended)

`/api/ask` can execute model-generated SQL. Three layers guard it: the validator in
`src/llm/nl2sql.py`, a `READ ONLY` transaction with a `statement_timeout`
(`src/db.py:read_sql_readonly`), and — the only one that does not depend on this
codebase being correct — a database role that simply cannot write.

Run once in the Supabase SQL editor, then point `DATABASE_URL` at `nhs_reader`
for the API. The publisher keeps using the owner role:

```sql
CREATE ROLE nhs_reader LOGIN PASSWORD '<strong-password>';
GRANT CONNECT ON DATABASE postgres TO nhs_reader;
GRANT USAGE ON SCHEMA public TO nhs_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nhs_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nhs_reader;
REVOKE CREATE ON SCHEMA public FROM nhs_reader;
```

---

## 1. API → Render (Docker)

1. Push this repo to GitHub.
2. Render → **New + → Blueprint** → select the repo (`render.yaml` is auto-detected).
3. Set the secret env vars: `DATABASE_URL` (Supabase pooler URI), `OPENROUTER_API_KEY`,
   `CORS_ORIGINS` (your Vercel URL).
4. Deploy. The image (`docker/Dockerfile.api`) honours Render's `$PORT`; health check `/api/health`.

→ `https://nhs-capacity-api.onrender.com`. Any container host works (Fly.io, Railway, Azure
Container Apps) — same image, same env vars, expose `$PORT`.

---

## 2. Frontend → Vercel

1. Vercel → **Add New → Project** → import the repo, **Root Directory = `frontend`**
   (`frontend/vercel.json` handles SPA routing).
2. Env var `VITE_API_BASE` = your Render API URL.
3. Deploy → `https://nhs-capacity.vercel.app` (**public URL**).

Ensure the API's `CORS_ORIGINS` includes the Vercel domain.

---

## 3. Local — one command (Docker Compose)

```bash
docker compose up -d --build      # frontend :8080 · api :8000 · db :5432
docker compose run --rm seed      # build gold warehouse + load Postgres (one-off)
```

Open <http://localhost:8080>. Set `DATABASE_URL` in `.env` to use Supabase instead of the
bundled Postgres.

---

## CI/CD

`.github/workflows/ci.yml` runs on every push: Python lint (ruff) + 16 tests + Docker build,
plus a frontend `npm ci && npm run build` job. Add a deploy hook (Render auto-deploy + Vercel
git integration) for continuous delivery.

---

## Reference — enterprise cloud (Azure, NHS-aligned)

| Component | Azure service |
|---|---|
| Ingestion | Azure Data Factory pipelines |
| Lake (Bronze/Silver) | ADLS Gen2 (partitioned parquet) |
| Warehouse (Gold) | Azure Database for PostgreSQL Flexible Server / Synapse |
| Compute | Azure Databricks (PySpark) — see `requirements-scale.txt` |
| ML | Azure ML Endpoints for Prophet/XGBoost/LightGBM |
| LLM | Azure OpenAI (private endpoint) or Anthropic via API |
| Frontend | Vercel / Azure Static Web Apps |
| API | Azure Container Apps |
| BI | Power BI Premium (DirectQuery to Postgres) |
| Auth | Entra ID (NHSmail), row-level security |

**Security & compliance:** DTAC-aligned — encryption at rest + in transit, RBAC, audit logging.
Operates on aggregate operational data (no PHI); LLM prompts carry no patient-identifiable data.
**Observability:** structured JSON logs (`src/utils/logging.py`); add OpenTelemetry traces
(SPA → API → DB/LLM) and Evidently AI for forecast drift.
