#!/usr/bin/env bash
# Acceptance test: clone the public repo into a fresh folder, build the env from
# scratch and run the whole pipeline, timing each step.
# Usage: bash scripts/clean_run.sh [repo_url] [target_dir]
set -euo pipefail
REPO_URL="${1:-https://github.com/edwinzhang98/retention-ab-test-analysis.git}"
TARGET="${2:-$(mktemp -d)/retention-ab-test-analysis}"

t() { date +%s; }
T0=$(t)
git clone --quiet "$REPO_URL" "$TARGET"
cd "$TARGET"
T1=$(t)
uv venv --quiet --python 3.12 .venv
uv pip install --quiet --python .venv/bin/python -r requirements.txt
T2=$(t)
.venv/bin/python run.py
T3=$(t)
echo "clone: $((T1-T0))s | env: $((T2-T1))s | pipeline: $((T3-T2))s | total: $((T3-T0))s"
echo "dir: $TARGET"
