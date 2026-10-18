#!/usr/bin/env bash
# ============================================================
#  Run all tests (macOS / Linux). Example: ./run_tests.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "[错误] 未找到 .venv，请先运行 ./setup.sh" >&2
  exit 1
fi
exec .venv/bin/python tests/run_tests.py
