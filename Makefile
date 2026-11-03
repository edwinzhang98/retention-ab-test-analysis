# One-command build. `make all` = setup check + full pipeline.
PY ?= .venv/bin/python

.PHONY: all setup pipeline analysis app clean

all: pipeline

setup:            ## create the virtual env and install pinned deps
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r requirements.txt

pipeline:         ## analysis -> SQL reconciliation -> figures -> notebooks -> report
	$(PY) run.py

analysis:         ## fast path: just recompute numbers + caches (no notebooks / report)
	$(PY) run.py --only analysis

app:              ## launch the Streamlit demo
	$(PY) -m streamlit run dashboard/app.py

clean:
	rm -rf data/processed reports/figures/*.png reports/notebooks/*.html reports/report.html
