# Deployment Plan

## A. Local Development (Docker Compose)

```bash
docker compose -f docker/docker-compose.yml up
```

Spins up:
* `nhs-app` — Streamlit on :8501
* `nhs-airflow` — Airflow on :8080
* `nhs-duckdb` — shared warehouse volume
* `nhs-redis` — caching for LLM responses

## B. Local (No Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run src/dashboard/app.py
```

## C. Cloud — Azure (recommended for NHS)

| Component | Azure Service |
|---|---|
| Ingestion | Azure Data Factory (mirrors `dags/nhs_etl_dag.py`) |
| Storage (Bronze/Silver) | ADLS Gen2 (parquet, partitioned) |
| Warehouse (Gold) | Azure Synapse Dedicated SQL Pool or PostgreSQL Flexible Server |
| Compute | Azure Databricks (PySpark) |
| Orchestration | Airflow on AKS or ADF pipelines |
| ML | Azure ML Endpoints for Prophet/XGBoost |
| LLM | Azure OpenAI Service (private, NHS DTAC compliant) |
| Dashboard | Streamlit on Azure App Service or AKS |
| BI | Power BI Premium, DirectQuery to Synapse |
| Auth | Entra ID (NHSmail), Row-Level Security |

## D. Cloud — AWS / GCP

* **AWS:** S3 (Bronze/Silver), Redshift (Gold), MWAA (Airflow), SageMaker (ML), Bedrock (LLM), ECS Fargate (Streamlit).
* **GCP:** GCS, BigQuery, Cloud Composer, Vertex AI, Gemini, Cloud Run.

## E. CI/CD

`.github/workflows/ci.yml`:
* Lint (`ruff`), type-check (`mypy`), test (`pytest`)
* Build Docker image
* Push to ACR/ECR/GHCR
* Deploy to staging via Helm / Terraform

## F. Observability

* OpenTelemetry traces from Streamlit → API → LLM.
* Evidently AI for ML drift on forecasts.
* Structured JSON logs (`src/utils/logging.py`).

## G. Security & Compliance

* DTAC aligned: encryption at rest + in transit, RBAC, audit log.
* No PHI: this platform operates on aggregate operational data.
* LLM calls go to private endpoint; no patient-identifiable data in prompts.
