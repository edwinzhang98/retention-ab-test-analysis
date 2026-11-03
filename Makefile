# One-command build. `make all` runs the full pipeline; `make setup` creates the environment.
PY ?= .venv/bin/python

.PHONY: all setup pipeline analysis sql notebooks app test clean

all: pipeline

setup:            ## create the virtual env and install pinned deps
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r requirements.txt

pipeline:         ## analysis -> SQL reconciliation -> figures -> notebooks -> report
	$(PY) run.py

analysis:         ## fast path: just recompute numbers + caches (no notebooks / report)
	$(PY) run.py --only analysis

sql:              ## run sql/*.sql in DuckDB and reconcile with reports/results.json
	$(PY) -m src.sql_check

notebooks:        ## regenerate the notebooks from scripts/notebooks/, then execute + export them
	$(PY) scripts/notebooks/build_01_eda.py
	$(PY) scripts/notebooks/build_02_retention.py
	$(PY) scripts/notebooks/build_03_ab_test.py
	$(PY) run.py --only notebooks

test:             ## dashboard smoke + interaction tests (Streamlit AppTest)
	$(PY) tests/test_dashboard_a.py
	$(PY) tests/test_dashboard_b.py

app:              ## launch the Streamlit demo
	$(PY) -m streamlit run dashboard/app.py

clean:
	rm -rf data/processed reports/figures/*.png reports/notebooks/*.html reports/report.html
