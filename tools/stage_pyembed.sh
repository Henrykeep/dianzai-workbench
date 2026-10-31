#!/usr/bin/env bash
# 自带嵌入版 CPython + 离线依赖（#112 后续）。package_windows.sh（Linux 交叉打包）和 .github/workflows/app-windows.yml（正式安装包）共用。
# 用法：bash tools/stage_pyembed.sh <输出目录>   → <输出目录>/python/、<输出目录>/wheelhouse/、<输出目录>/安装离线依赖.bat
# PY=宿主 python（默认 python3，没有就 python）；Linux 和 Windows（Git Bash）上都能跑：pip 按目标平台 win_amd64/cp312 下载并 --target 装
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
STAGE=$1
PYVER=3.12.10
PY=${PY:-$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)}
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
# 官方 embeddable zip（python.org，钉版本 + sha256）解到 <安装目录>/python/；用户机器上的 Python 版本不再影响离线安装
source "$ROOT/tools/fetch_lib.sh"
PYEMBED_URL="https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
PYEMBED_SHA=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3
fetch_url "$PYEMBED_URL" "$WORK/pyembed.zip" "$PYEMBED_SHA" || { echo "✗ [pyembed] 嵌入版 Python 下载或 sha256 校验失败"; exit 1; }
mkdir -p "$STAGE/python" && (cd "$STAGE/python" && unzip -q "$WORK/pyembed.zip")
"$PY" "$ROOT/tools/pyembed.py" pth "$STAGE/python/python$(echo "${PYVER%.*}" | tr -d .)._pth"   # 打开 site-packages（嵌入版默认关掉）
PYTAG=${PYVER%.*}
mkdir -p "$STAGE/wheelhouse/_pip"
grep -v '^\s*#' "$ROOT/tools/wheelhouse.txt" | sed 's/\s*#.*//' | sed '/^\s*$/d' > "$STAGE/wheelhouse/requirements.txt"
"$PY" -m pip download --only-binary=:all: --platform win_amd64 --python-version "$PYTAG" --implementation cp \
  -d "$STAGE/wheelhouse" -r "$STAGE/wheelhouse/requirements.txt" >/dev/null
"$PY" -m pip download --only-binary=:all: --no-deps -d "$STAGE/wheelhouse/_pip" pip==25.0.1 >/dev/null   # 嵌入版没有 pip；.bat 从这个 wheel 直接跑 pip
"$PY" "$ROOT/tools/pyembed.py" manifest "$STAGE/wheelhouse" "$PYTAG" win_amd64 "$STAGE/wheelhouse/requirements.txt"
# 打包时就离线装进自带解释器（本机 pip 按目标平台装，不联网）；.bat 只是用户误删后的补救
"$PY" -m pip install --no-index --find-links "$STAGE/wheelhouse" --only-binary=:all: --platform win_amd64 \
  --python-version "$PYTAG" --implementation cp --target "$STAGE/python/Lib/site-packages" \
  -r "$STAGE/wheelhouse/requirements.txt" >/dev/null
# 补救 .bat：用自带解释器跑 pydeps.py repair（离线重装；pip 英文报错翻成中文说明，#137）
printf '%s\r\n' '@echo off' 'chcp 65001 >nul' 'rem 离线重装 Python 依赖（不联网）到安装目录自带的 python\python.exe' \
  'set PYTHONUTF8=1' '"%~dp0python\python.exe" "%~dp0repo\tools\pydeps.py" repair' 'pause' > "$STAGE/安装离线依赖.bat"
echo "✓ 嵌入版 Python $PYVER → $STAGE/python（site-packages 已装好），wheelhouse + manifest.json → $STAGE/wheelhouse"
