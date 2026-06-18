.PHONY: install pipeline publish stream api web test lint

install:
	pip install -r requirements.txt

# Build the medallion gold warehouse (bronze→silver→gold→train→risk→recommend)
pipeline:
	python scripts/run_pipeline.py

# Publish the gold warehouse into PostgreSQL (set DATABASE_URL first)
publish:
	python scripts/publish_to_postgres.py

# Real-time A&E ingestion simulation
stream:
	python scripts/run_stream_sim.py

# FastAPI backend (serves the React frontend + Power BI from Postgres)
api:
	uvicorn src.api.main:app --reload

# React + Tailwind frontend (dev server, proxies /api → :8000)
web:
	cd frontend && npm install && npm run dev

test:
	pytest tests/

lint:
	ruff check src/ tests/
