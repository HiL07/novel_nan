#!/usr/bin/env bash
# ============================================================
#  novel-deai-tomato-pass  one-click setup (macOS / Linux)
#  Creates .venv and installs python-docx. Run once before use.
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=""
if command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "[错误] 未找到 Python。请先安装 Python 3.9+ 后再运行。" >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "创建虚拟环境 .venv ..."
  "$PY" -m venv .venv
fi

echo "安装依赖 python-docx ..."
.venv/bin/python -m pip install -r requirements.txt

echo ""
echo "完成。用法："
echo "  ./run.sh scripts/extract_docx.py <input.docx> out.txt"
echo "  ./run_tests.sh"
echo ""
