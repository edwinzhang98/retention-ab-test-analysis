"""Capture a screenshot of every Streamlit page for the README.

Usage (from the repo root, after `python run.py --only analysis`):
    python scripts/capture_screenshots.py            # starts the app on port 8650, saves PNGs, stops it
    python scripts/capture_screenshots.py --channel chromium   # use Playwright's bundled Chromium instead of system Chrome

Output: reports/screenshots/<page>.png
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "screenshots"
PAGES = [
    ("overview", "1_overview"),
    ("data-sanity", "2_data_sanity"),
    ("retention", "3_retention"),
    ("experiment", "4_experiment_readout"),
    ("heterogeneity", "5_heterogeneity"),
    ("gate", "6_gate_experiment"),
    ("decision", "7_decision"),
]


def wait_for(url: str, timeout: float = 60) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return time.time() - t0
        except Exception:
            time.sleep(0.3)
    raise TimeoutError(url)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8650)
    ap.add_argument("--channel", default="chrome", help="'chrome' (system Chrome) or 'chromium' (playwright install chromium)")
    ap.add_argument("--width", type=int, default=1400)
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard/app.py", "--server.port", str(a.port),
                             "--server.headless", "true"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        base = f"http://localhost:{a.port}"
        wait_for(base)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=None if a.channel == "chromium" else a.channel)
            page = browser.new_page(viewport={"width": a.width, "height": 1000}, device_scale_factor=1)
            for slug, name in PAGES:
                t0 = time.time()
                page.goto(f"{base}/{slug}")
                page.wait_for_selector("h1", timeout=30_000)
                page.wait_for_selector(".js-plotly-plot", timeout=30_000)
                page.wait_for_timeout(1500)  # let remaining charts finish drawing
                errors = page.locator("[data-testid='stException']").count()
                path = OUT / f"{name}.png"
                page.screenshot(path=str(path))  # first screen, as the viewer lands on the page
                print(f"{name}: {time.time() - t0:.1f}s to render, exceptions={errors} -> {path.relative_to(ROOT)}")
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    main()
