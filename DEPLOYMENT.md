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
| Ingestion | Azure Data Factory (mirrors `dags/nhs_etl_dag.py`) |
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
