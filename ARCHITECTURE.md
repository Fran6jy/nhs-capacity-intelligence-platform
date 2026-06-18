# Architecture & Design

## 1. Layered System

| Layer | Technology | Responsibility |
|---|---|---|
| **Sources** | NHS England API, HES, WFS, ONS, Met Office, GOV.UK flu/COVID | Operational & contextual data |
| **Ingestion** | Python, Airflow, (Azure Data Factory compatible) | Scheduled / event-driven pulls |
| **Storage — Bronze** | Parquet (raw) | Immutable, partitioned by source/date |
| **Storage — Silver** | Parquet (cleaned) | Typed, deduped, joined to reference |
| **Storage — Gold** | DuckDB / Postgres / Synapse | Star schema, analytics-ready |
| **Feature Engineering** | PySpark (Spark), Pandas fallback | Rolling means, lags, seasonal flags, regional z-scores |
| **ML Serving** | Prophet, XGBoost, LightGBM | 30/60/90-day forecasts |
| **Risk Engine** | NumPy/SciPy composite | Weighted G/A/R classification |
| **LLM Layer** | OpenAI API (or local Ollama) + LangChain | NL→SQL, RAG, multi-agent |
| **Dashboard** | Streamlit, Power BI | Interactive & executive views |

---

## 2. Data Flow

```
SOURCES ──► [Airflow] ──► data/raw/*.parquet  (🥉)
                              │
                              ▼  silver.py (clean, dedupe, type)
                  data/processed/*.parquet      (🥈)
                              │
                              ▼  gold.py (star schema)
                       warehouse.duckdb          (🥇)
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
       ML models         Risk engine      LLM RAG
            │                 │                 │
            └──────►  Streamlit app  ◄──────────┘
                         Power BI
```

---

## 3. Star Schema

```
                  dim_date ───┐
                              │
   dim_specialty ──►┐         │
                    │         │
   dim_region ──►┐  │         │
                │  │         │
            hospital_activity_fact
                │  │         │
                │  │         │
   dim_hospital ┴──┴─────────┘
```

* **fact**: `hospital_activity_fact` (date, hospital, specialty, admissions, discharges, bed_occupancy, waiting_list_size, staff_count, vacancies, ae_attendances)
* **dim_date**: date, year, month, day_of_week, week, quarter, is_weekend, season, flu_season_flag
* **dim_hospital**: hospital_id, name, region, trust_code, type, bed_capacity
* **dim_specialty**: specialty_id, name, category, is_emergency
* **dim_region**: region_id, name, country, icb, population

---

## 4. ML Strategy

| Model | Use | Algorithm | Why |
|---|---|---|---|
| Bed occupancy forecast | 30/60/90-day | Prophet (seasonality) + XGBoost (with lags, weather, flu) | Prophet handles holidays/seasonality; XGBoost for multivariate |
| Waiting time forecast | specialty × trust | LightGBM with lag + workforce features | Handles many features well |
| Workforce demand | trust × role | XGBoost regressor | Strong on tabular |
| A&E demand | trust | Prophet (daily) | Strong daily/weekly seasonality |

All models write forecasts back to `gold.ml_forecast` table for unified consumption.

---

## 5. Risk Engine

```
score = 0.30 * z(bed_occupancy_pct)
      + 0.30 * z(waiting_list_growth_30d)
      + 0.25 * z(vacancy_rate)
      + 0.15 * z(ae_surge_index)
```

| Score | Classification |
|---|---|
| < 0.0 | 🟢 Green |
| 0.0 – 1.0 | 🟡 Amber |
| ≥ 1.0 | 🔴 Red |

Computed daily per `hospital_id`, also aggregated to region.

---

## 6. LLM / RAG Architecture

1. **Question received** by `InsightAgent`.
2. **NL→SQL** module (LangChain `create_sql_query_chain` + SQL guard-rails) generates a read-only query.
3. **SQL validator** ensures: SELECT only, references approved tables, parameterized.
4. **Executor** runs the query against DuckDB.
5. **RAG context builder** packages rows + recent forecasts + risk + meta into a prompt.
6. **LLM** (OpenAI `gpt-4o-mini` or local) generates a structured response: explanation, quantified insight, forecast, recommendations.
7. **Multi-agent** fan-out: Forecaster, Workforce, Risk, and Executive agents collaborate to synthesise the final answer.

---

## 7. Recommendation Engine

Rule + LLM hybrid. For each Red/Amber trust we surface:

* **Staffing:** fill vacancy hot-spots
* **Capacity:** open surge beds
* **Workload:** redistribute elective lists
* **Pathway:** shift to community diagnostics

---

## 8. Scalability

* **Local MVP:** DuckDB, single-machine.
* **Production:** Synapse/Postgres, Spark cluster, Airflow on K8s, Streamlit on Azure App Service or AKS.
* **Streaming:** swap Airflow for Kafka + Spark Structured Streaming, keep downstream unchanged.
