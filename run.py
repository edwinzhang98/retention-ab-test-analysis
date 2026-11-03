"""One command to rebuild everything: python run.py  (or: make all)

Steps
  1. analysis   read raw CSVs -> clean -> all tests -> data/processed/*.parquet, reports/results.json, reports/tables/
  2. sql        run every sql/*.sql in DuckDB and reconcile against results.json
  3. figures    static PNGs for README / docs (reports/figures/)
  4. notebooks  execute notebooks/*.ipynb in place and export HTML to reports/notebooks/
  5. report     reports/report.html (standalone, interactive Plotly)

Usage: python run.py [--skip-notebooks] [--only analysis,sql,figures,notebooks,report]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

STEPS = ["analysis", "sql", "figures", "notebooks", "report"]


def step_analysis():
    from src.analysis import build_all
    build_all()


def step_sql():
    from src.sql_check import run_and_reconcile
    run_and_reconcile()


def step_figures():
    from src.analysis import load_results
    from src.catalog import build_catalog, load_caches, save_pngs
    paths = save_pngs(build_catalog(load_results(), load_caches()))
    print(f"[figures] wrote {len(paths)} PNGs to reports/figures/")


def step_notebooks():
    out_dir = ROOT / "reports" / "notebooks"
    out_dir.mkdir(parents=True, exist_ok=True)
    for nb in sorted((ROOT / "notebooks").glob("[0-9][0-9]_*.ipynb")):
        t0 = time.time()
        subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                        "--ExecutePreprocessor.timeout=600", "--ExecutePreprocessor.kernel_name=python3", str(nb)],
                       check=True, cwd=ROOT)
        subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "html", "--output-dir", str(out_dir),
                        str(nb)], check=True, cwd=ROOT)
        print(f"[notebooks] {nb.name} executed + exported in {time.time() - t0:.0f}s")


def step_report():
    from src.report import build_report
    path = build_report()
    print(f"[report] wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(STEPS))
    ap.add_argument("--skip-notebooks", action="store_true")
    a = ap.parse_args()
    steps = [s for s in a.only.split(",") if s]
    if a.skip_notebooks and "notebooks" in steps:
        steps.remove("notebooks")
    t_all = time.time()
    for s in STEPS:
        if s in steps:
            t0 = time.time()
            print(f"==> {s}")
            globals()[f"step_{s}"]()
            print(f"    {s} done in {time.time() - t0:.1f}s")
    print(f"All done in {time.time() - t_all:.1f}s")


if __name__ == "__main__":
    main()
