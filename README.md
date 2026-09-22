# NHS Capacity & Demand Intelligence Platform

A production-grade analytics + AI platform that shifts NHS operations from **reactive reporting** to **predictive + prescriptive intelligence**.

> Ingests NHS operational data → forecasts A&E demand, bed occupancy, workforce gaps, and waiting times → surfaces insights via a React web app, an LLM-powered RAG chat, and Power BI.

---

## 🎯 What This Platform Does

| Capability | Description |
|---|---|
| **Predictive forecasting** | 30/60/90-day bed occupancy, waiting time, A&E demand, workforce shortage forecasts (Prophet + XGBoost + LightGBM) |
| **Composite Risk Score** | Operational pressure classified Green / Amber / Red from a peer-relative composite (waiting list growth, bed occupancy %, vacancy rate, A&E surge), plus an absolute safety overlay so system-wide surges still escalate — final verdict is the worse of the two |
| **LLM Insight Layer** | Natural-language → SQL → context → LLM explanation (RAG), routed through three trust tiers: a reviewed query when one covers the question, model-generated SQL against the live schema for the long tail, and an explicit refusal rather than a guess. Every answer returns the SQL that produced it. Multi-agent system with Forecasting, Workforce, Risk, and Executive agents |
| **Recommendation Engine** | Prescriptive actions: surge capacity, staffing redistribution, workload balancing |
| **Streaming-Ready** | Medallion (Bronze/Silver/Gold) architecture on DuckDB / Postgres / Synapse, pluggable Kafka ingestion |

---

## 🏗️ Architecture

```
                 ┌─────────────────────────────────────────────────────┐
                 │  SOURCES (NHS ENGLAND API, HES, WFS, ONS, MET OFF) │
                 └────────────────────────┬────────────────────────────┘
                                          │  batch / streaming
                                          ▼
              ┌──────────────────────────────────────────────────────┐
              │  INGESTION  (Python · Airflow · Azure Data Factory)  │
              │  • NHS waiting lists   • HES episodes                │
              │  • Workforce stats     • Demographics                 │
              │  • Flu / COVID trends  • Weather                      │
              └────────────────────────┬─────────────────────────────┘
                                       ▼
            ╔══════════════════════════════════════════════════════╗
            ║             MEDALLION DATA LAKE                      ║
            ║  🥉 Bronze (raw, partitioned parquet)                 ║
            ║  🥈 Silver (cleaned, deduped, typed)                 ║
            ║  🥇 Gold   (analytics-ready star schema)             ║
            ╚══════════════════════════════════════════════════════╝
                                       ▼
   ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
   │  ML FORECASTING │  │  RISK ENGINE    │  │  RAG + LLM LAYER │
   │  Prophet/XGBoost│  │  Composite idx  │  │  NL→SQL + LLM    │
   │  LightGBM       │  │  G/A/R classify │  │  Multi-agent     │
   └────────┬────────┘  └────────┬────────┘  └────────┬─────────┘
            └─────────────┬──────┴──────────┬──────────┘
                          ▼                 ▼
              ┌──────────────────────┐  ┌──────────────────────┐
              │  REACT WEB APP       │  │  POWER BI EXECUTIVE  │
              │  • Exec Overview     │  │  reports             │
              │  • Forecasts         │  │                      │
              │  • Workforce         │  │                      │
              │  • AI Chat           │  │                      │
              └──────────────────────┘  └──────────────────────┘
```

---

## 📁 Project Structure

```
nhs-capacity-platform/
├── README.md                         # this file
├── ARCHITECTURE.md                   # detailed design + data flow
├── DEPLOYMENT.md                     # local + cloud deployment plan
├── OPERATIONS.md                     # running it: routines, security, runbook
├── pyproject.toml                    # deps
├── requirements.txt
├── .env.example
├── Makefile
│
├── data/
│   ├── raw/                          # 🥉 Bronze
│   ├── processed/                    # 🥈 Silver
│   └── gold/                         # 🥇 Gold
│
├── src/
│   ├── __init__.py
│   ├── config.py                     # settings
│   ├── ingestion/                    # data acquisition
│   │   ├── nhs_england.py            # REAL monthly RTT + A&E open data
│   │   ├── ods.py                    # REAL live NHS trust roster
│   │   ├── nhs_api.py
│   │   ├── hes_client.py
│   │   ├── workforce.py
│   │   ├── population.py
│   │   ├── illness_trends.py
│   │   └── weather.py
│   ├── pipeline/                     # ETL/ELT
│   │   ├── bronze.py
│   │   ├── silver.py
│   │   ├── gold.py
│   │   ├── nhs_real.py               # real NHS monthly tables (own grain)
│   │   └── features.py
│   ├── db.py                         # SQLAlchemy/PostgreSQL data layer
│   ├── api/                          # FastAPI backend (serves from Postgres)
│   │   ├── main.py
│   │   └── schemas.py
│   ├── streaming/                    # real-time A&E ingestion (Kafka / in-memory)
│   │   ├── events.py
│   │   ├── bus.py
│   │   ├── producer.py
│   │   └── consumer.py
│   ├── models/                       # ML
│   │   ├── bed_occupancy.py
│   │   ├── waiting_time.py
│   │   ├── workforce_demand.py
│   │   ├── ae_demand.py
│   │   └── training.py
│   ├── risk/                         # composite score
│   │   └── risk_engine.py
│   ├── llm/                          # RAG + agents
│   │   ├── rag.py
│   │   ├── nl2sql.py
│   │   ├── agents.py
│   │   ├── recommender.py
│   │   └── prompts.py
│   └── utils/
│       ├── logging.py
│       ├── io.py
│       └── dates.py
│
├── notebooks/                        # exploration
│   ├── 01_eda.ipynb
│   └── 02_model_eval.ipynb
│
├── sql/
│   ├── 01_warehouse.sql              # star schema DDL
│   └── 02_analytics_views.sql
│
├── powerbi/
│   └── README.md                     # PBIX connect instructions
│
├── tests/                            # 58 tests, enforced in CI
│   ├── test_pipeline.py
│   ├── test_models.py
│   ├── test_risk.py
│   ├── test_rag.py                   # NL→SQL tiers, validator, refusal
│   ├── test_nhs_england.py           # real-data parsing traps
│   ├── test_api_ask.py               # HTTP contract
│   ├── test_config.py                # DB URL resolution
│   ├── test_check_database_url.py
│   ├── test_db.py
│   ├── test_api_health.py
│   └── test_streaming.py
│
├── frontend/                         # React + TypeScript + Tailwind SPA
│   └── src/{pages,components,lib}
│
├── docker/
│   └── Dockerfile.api                # FastAPI image
├── docker-compose.yml                # Postgres + API + frontend
├── render.yaml                       # API deploy (Render)
│
├── scripts/
│   ├── run_pipeline.py               # end-to-end pipeline runner
│   ├── publish_to_postgres.py        # load gold → PostgreSQL + harden()
│   ├── ingest_nhs_real.py            # MONTHLY: real NHS data (run locally)
│   ├── check_database_url.py         # connection preflight
│   ├── check_reader_role.py          # prove the read-only role works
│   └── run_stream_sim.py             # streaming simulation
│
└── .github/
    └── workflows/
        ├── ci.yml
        ├── refresh.yml               # 12-hourly data refresh
        └── deploy.yml
```

---

## 🚀 Quick Start

```bash
# 1. Install
git clone <repo> nhs-capacity-platform
cd nhs-capacity-platform
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt                     # lean, runnable core
# Optional scale-out infra (Airflow, PySpark, Postgres) + alt LLM backends:
# pip install -r requirements-scale.txt
cp .env.example .env                                # add your ANTHROPIC_API_KEY (Claude is the default provider)

# 2. Run the whole pipeline end-to-end:
#    bronze → silver → gold (star schema) → train models → risk scores → recommendations
python scripts/run_pipeline.py

# 3a. Publish the gold warehouse into PostgreSQL (system-of-record)
#     Point DATABASE_URL at your managed Postgres (Azure/RDS/Supabase) or a local one.
export DATABASE_URL=postgresql+psycopg2://nhs:password@localhost:5432/nhs_warehouse
python scripts/publish_to_postgres.py

# 3b. Run the FastAPI backend (serves the React frontend + Power BI from Postgres)
uvicorn src.api.main:app --reload          # http://localhost:8000/docs

# 3c. Launch the React + Tailwind frontend (immersive enterprise UI)
cd frontend && npm install && npm run dev      # http://localhost:5173 (proxies /api -> :8000)


# 4. (Optional) Real-time A&E ingestion — batch simulation or live Kafka
python scripts/run_stream_sim.py --events 3000 --rate 1500
#   Producer + micro-batching consumer stream A&E attendances onto a pluggable
#   bus and maintain a live `ae_stream_agg` table in the warehouse.
#   Set STREAM_BACKEND=kafka + KAFKA_BOOTSTRAP=host:9092 to run against a real broker.
```

Open <http://localhost:5173> (Vite dev server; the API runs on :8000).

### Real vs modelled data

Real, ingested from published sources — no credentials required:

| Source | What it gives |
|---|---|
| **NHS England RTT** | Monthly incomplete-pathway waiting list by provider and treatment function (~7.2M pathways, 533 providers, 23 specialties) |
| **NHS England A&E** | Monthly attendances, four-hour breaches, 12-hour DTA waits and emergency admissions by provider (~2.3M attendances, 182 providers) |
| **NHS ODS** | Live register of active NHS trusts |
| **Open-Meteo** | Daily mean temperature per NHS region |

Modelled: the daily activity fact table, the A&E digital twin, workforce and
demographics. NHS England publishes monthly, so anything at daily or minute
grain is necessarily modelled — the Evidence & Validation page states which is
which, per source, rather than blurring the line.

> **Note:** Every external source has a synthetic fallback, so the full pipeline runs offline with no
> NHS/ONS/Met Office credentials. The LLM layer defaults to **Claude** (`LLM_PROVIDER=anthropic`); with no
> API key it falls back to a local echo model so the web app and RAG chat still function. Set
> `LLM_PROVIDER=openai|azure|ollama` to switch providers.

---

## 🧠 Example LLM Insight

Verbatim from the deployed `/api/ask`, not an illustration:

**Q:** "Why are waiting times rising?"

> **Explanation**: Waiting times are not rising — they have fallen across all ten
> specialties over the last 90 days, with median waits decreasing by 1.1–1.8 days.
>
> **Quantified insight**:
> - Trauma & Orthopaedics and General Medicine saw the largest drops: median wait fell
>   from 22.1 to 20.3 days and from 21.5 to 19.8 days respectively (−1.8 days each).
> - The smallest improvement was in General Surgery, down from 17.4 to 16.3 days.

The assistant **contradicts the question's premise** rather than explaining a trend
that isn't happening. Three properties make that possible:

1. **Tiered routing.** A reviewed query answers what it covers; model-generated SQL
   handles the long tail; anything neither can answer is **refused**, not guessed.
   Ask it the capital of France and it says what it can answer instead.
2. **Trend data, not snapshots.** The waiting-times query returns now, 90 days ago,
   and the change — so "why is X rising" is answerable, including with "it isn't".
3. **Auditable provenance.** Every answer returns the SQL that produced it, badged
   *Verified query* or *AI-generated SQL — check before relying on this figure*.

---

## 🔧 Running it in production

Day-to-day operations, the security model and a failure runbook live in
[`OPERATIONS.md`](OPERATIONS.md). The two things worth knowing up front:

* **The warehouse refreshes itself** every 12 hours via GitHub Actions — models,
  risk scores, digital twin and all — and re-applies the database security posture
  on each run.
* **The real NHS England data is refreshed by hand, monthly.** NHS England publish on
  the **second Thursday**; their WAF blocks datacentre IPs, so CI cannot fetch it:

  ```powershell
  python scripts/ingest_nhs_real.py
  ```

  See [`OPERATIONS.md` §3](OPERATIONS.md) for the full routine and the verification step.

---

## 🛡️ Design Principles

* **Modular & production-like** — clear separation of ingestion / pipeline / models / serving.
* **Medallion architecture** — bronze/silver/gold; reproducible transformations.
* **Star schema warehouse** — analytics-optimized joins.
* **Hybrid ML** — Prophet for univariate seasonality, XGBoost/LightGBM for multivariate + lags.
* **Agentic LLM** — NL→SQL behind three trust tiers; a refusal beats a plausible guess.
* **Least privilege at runtime** — the API connects with a role that cannot write, so a
  flaw in the query layer cannot mutate the warehouse.
* **Security as code** — RLS and grants are re-applied by the publisher on every run,
  because a posture set by hand erodes the moment a table is recreated.
* **Honest provenance** — real and modelled sources are labelled per source, in the UI,
  rather than blurred together.
* **Local-first** — runs entirely on DuckDB for an MVP, scales to Postgres/Synapse.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for design, [`DEPLOYMENT.md`](DEPLOYMENT.md)
for first-time setup, and [`OPERATIONS.md`](OPERATIONS.md) for running it.

---
