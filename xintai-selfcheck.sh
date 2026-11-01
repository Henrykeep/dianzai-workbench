#!/usr/bin/env bash
# 芯台自检（Linux / macOS 源码运行）。
# 选 Python：设了 $PYTHON 就只用它；否则按 自带解释器 → .venv/bin/python → python3.12 → python3.13 → python3.11 → python3 → python
# 逐个探测，挑第一个侧车依赖（tools/wheelhouse-sidecar.txt）都能 import 的（#157）。
# 都不齐 → 中文列出每个解释器缺哪些模块，提示 PYTHON=… 和离线依赖修复办法，退出码 3（未完成），不是 1。
cd "$(dirname "$0")" || exit 1
REQ=tools/wheelhouse-sidecar.txt
# 包名 → import 名（与 tools/pydeps.py 的 IMPORT_NAME 一致）
mods() {
  sed -e 's/#.*//' -e 's/[=<>~!; ].*//' "$REQ" | while read -r n; do
    [ -n "$n" ] || continue
    case "$(echo "$n" | tr 'A-Z' 'a-z')" in
      pyserial) echo serial ;; pyyaml) echo yaml ;; *) echo "$n" | tr 'A-Z-' 'a-z_' ;;
    esac
  done
}
MODS=$(mods | tr '\n' ' ')
PROBE='import importlib,sys
bad=[]
for m in sys.argv[1:]:
    try: importlib.import_module(m)
    except Exception: bad.append(m)
print("MISSING:"+" ".join(bad))'
probe() {  # $1 = 解释器；输出缺的模块（空=齐），探测本身失败返回 1
  local out
  if command -v timeout >/dev/null 2>&1; then
    out=$(PYTHONPATH= timeout 20 "$1" -c "$PROBE" $MODS 2>/dev/null) || return 1
  else
    out=$(PYTHONPATH= "$1" -c "$PROBE" $MODS 2>/dev/null) || return 1
  fi
  out=$(printf '%s\n' "$out" | grep '^MISSING:' | tail -1) || return 1
  printf '%s' "${out#MISSING:}"
}
FIX="修复办法：在仓库根目录执行 python3.12 -m venv .venv && .venv/bin/pip install -r tools/wheelhouse.txt -r $REQ（离线：.venv/bin/pip install --no-index --find-links <安装目录>/wheelhouse -r $REQ），或用 PYTHON=/path/to/python ./xintai-selfcheck.sh 指定一个依赖齐全的 Python。"
PY=
if [ -n "${PYTHON:-}" ]; then
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "[失败] PYTHON=$PYTHON 找不到或不可执行。"; exit 1
  fi
  PY=$PYTHON   # 用户指定的就用它；缺依赖由 selfcheck.py 报中文原因
else
  report=; found=0
  for c in ../python/bin/python3 python/bin/python3 .venv/bin/python python3.12 python3.13 python3.11 python3 python; do
    command -v "$c" >/dev/null 2>&1 || continue
    found=1
    if miss=$(probe "$c"); then
      if [ -z "${miss// /}" ]; then PY=$c; break; fi
      report="$report  - $c（$(command -v "$c")）缺：$miss"$'\n'
    else
      report="$report  - $c（$(command -v "$c")）无法运行或探测超时"$'\n'
    fi
  done
  if [ -z "$PY" ]; then
    if [ $found -eq 0 ]; then
      echo "[失败] 找不到 Python。请先安装 Python 3.12。$FIX"; exit 1
    fi
    echo "[未完成] 找到了 Python，但没有一个装齐侧车依赖（$MODS）："
    printf '%s' "$report"
    echo "$FIX"
    exit 3
  fi
fi
"$PY" tools/selfcheck.py
rc=$?
if [ -t 0 ] && [ -z "${DZ_NOPAUSE:-}" ]; then read -r -p "按回车键退出…" _ || true; fi
exit $rc
