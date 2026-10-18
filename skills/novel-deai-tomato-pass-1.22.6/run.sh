#!/usr/bin/env bash
# ============================================================
#  Unified entry: ./run.sh <script.py> [args...]
#  Example: ./run.sh scripts/extract_docx.py in.docx out.txt
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "[错误] 未找到 .venv，请先运行 ./setup.sh" >&2
  exit 1
fi
exec .venv/bin/python "$@"
