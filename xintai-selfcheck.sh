#!/usr/bin/env bash
# 芯台自检（Linux / macOS 源码运行）。选 Python 的顺序：$PYTHON → .venv/bin/python → python3.12 → python3 → python
# 先跑依赖自检：缺包 / 版本不对就打印中文原因和办法，退出码非 0，不往下跑。
cd "$(dirname "$0")" || exit 1
PY=${PYTHON:-}
if [ -z "$PY" ]; then
  for c in .venv/bin/python python3.12 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY=$c; break; fi
  done
fi
if [ -z "$PY" ] || ! command -v "$PY" >/dev/null 2>&1; then
  echo "[失败] 找不到 Python。请先安装 Python 3.12，在仓库根目录执行 python3.12 -m venv .venv && .venv/bin/pip install -r tools/wheelhouse.txt -r tools/wheelhouse-sidecar.txt，再运行本自检。"
  exit 1
fi
"$PY" tools/selfcheck.py
rc=$?
if [ -t 0 ] && [ -z "${DZ_NOPAUSE:-}" ]; then read -r -p "按回车键退出…" _ || true; fi
exit $rc
