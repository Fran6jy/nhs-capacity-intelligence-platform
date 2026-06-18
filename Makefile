.PHONY: install seed bronze silver gold train risk run test lint

install:
	pip install -r requirements.txt

seed:
	python scripts/seed_warehouse.py

bronze:
	python -m src.pipeline.bronze

silver:
	python -m src.pipeline.silver

gold:
	python -m src.pipeline.gold

train:
	python scripts/train_models.py

risk:
	python -m src.risk.risk_engine

run:
	streamlit run src/dashboard/app.py

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/
