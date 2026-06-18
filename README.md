# NHS Capacity & Demand Intelligence Platform

A production-grade analytics + AI platform that shifts NHS operations from **reactive reporting** to **predictive + prescriptive intelligence**.

> Ingests NHS operational data → forecasts A&E demand, bed occupancy, workforce gaps, and waiting times → surfaces insights via LLM-powered RAG chat + Streamlit & Power BI dashboards.

---

## 🎯 What This Platform Does

| Capability | Description |
|---|---|
| **Predictive forecasting** | 30/60/90-day bed occupancy, waiting time, A&E demand, workforce shortage forecasts (Prophet + XGBoost + LightGBM) |
| **Composite Risk Score** | Operational pressure classified Green / Amber / Red using waiting list growth, bed occupancy %, vacancy rate, A&E surge |
| **LLM Insight Layer** | Natural-language → SQL → context → LLM explanation (RAG). Multi-agent system with Forecasting, Workforce, Risk, and Executive agents |
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
              │  STREAMLIT DASHBOARD │  │  POWER BI EXECUTIVE  │
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
├── dags/                             # Airflow DAGs
│   └── nhs_etl_dag.py
│
├── src/
│   ├── __init__.py
│   ├── config.py                     # settings
│   ├── ingestion/                    # data acquisition
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
│   │   └── features.py
│   ├── warehouse/                    # star schema
│   │   ├── schema.sql
│   │   ├── duckdb_client.py
│   │   └── seed.py
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
│   ├── dashboard/                    # Streamlit
│   │   ├── app.py
│   │   ├── pages/
│   │   │   ├── 1_Executive_Overview.py
│   │   │   ├── 2_Forecasting.py
│   │   │   ├── 3_Workforce.py
│   │   │   ├── 4_AI_Chat.py
│   │   │   └── 5_Risk_Map.py
│   │   └── components/
│   │       ├── kpi_card.py
│   │       ├── risk_badge.py
│   │       └── forecast_chart.py
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
├── tests/
│   ├── test_pipeline.py
│   ├── test_models.py
│   ├── test_risk.py
│   └── test_rag.py
│
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── scripts/
│   ├── run_pipeline.py               # end-to-end runner
│   ├── train_models.py
│   ├── seed_warehouse.py
│   └── launch_streamlit.sh
│
└── .github/
    └── workflows/
        └── ci.yml
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

# 3. Launch dashboard
streamlit run src/dashboard/app.py

# 4. (Optional) Real-time A&E ingestion — batch simulation or live Kafka
python scripts/run_stream_sim.py --events 3000 --rate 1500
#   Producer + micro-batching consumer stream A&E attendances onto a pluggable
#   bus and maintain a live `ae_stream_agg` table in the warehouse.
#   Set STREAM_BACKEND=kafka + KAFKA_BOOTSTRAP=host:9092 to run against a real broker.
```

Open <http://localhost:8501>.

> **Note:** Every external source has a synthetic fallback, so the full pipeline runs offline with no
> NHS/ONS/Met Office credentials. The LLM layer defaults to **Claude** (`LLM_PROVIDER=anthropic`); with no
> API key it falls back to a local echo model so the dashboard and RAG chat still function. Set
> `LLM_PROVIDER=openai|azure|ollama` to switch providers.

---

## 🧠 Example LLM Insights

**Q:** "Why are cardiology waiting times increasing?"

**A:** "Cardiology waiting times are increasing due to an **18% rise in referrals** combined with a **7% reduction in consultant capacity**. If trends continue, waiting times will increase by **~12 days within 60 days**. Recommended actions: (1) open surge outpatient capacity, (2) redeploy 4 consultants from low-pressure trusts, (3) expand community diagnostic hubs."

---

## 🛡️ Design Principles

* **Modular & production-like** — clear separation of ingestion / pipeline / models / serving.
* **Medallion architecture** — bronze/silver/gold; reproducible transformations.
* **Star schema warehouse** — analytics-optimized joins.
* **Hybrid ML** — Prophet for univariate seasonality, XGBoost/LightGBM for multivariate + lags.
* **Agentic LLM** — NL→SQL guard-railed by SQL validation; multi-agent orchestration.
* **Local-first** — runs entirely on DuckDB for an MVP, scales to Postgres/Synapse.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`DEPLOYMENT.md`](DEPLOYMENT.md) for details.

---
