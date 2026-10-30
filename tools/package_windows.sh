#!/usr/bin/env bash
# 在 Linux 上交叉打 Windows 便携包（GitHub Actions 不可用时的替代；正式发布仍走 .github/workflows/app-windows.yml）
# 依赖：mingw-w64、wine（装好 Windows Python 3.12 到 C:\py312，并 pip 装 requirements + pyinstaller）、
#       rustup target x86_64-pc-windows-gnu、node/npm、zip、curl
# 产物：dist/电赛工作台-<版本>-win64-portable.zip
#   电赛工作台.exe          Tauri 外壳（windows-gnu）
#   dzbench.exe            侧车（PyInstaller，wine 里打）
#   python/                Windows 嵌入版 Python + pyyaml/jsonschema（项目页跑 tools/*.py 用）
#   repo/                  工程仓库子集（git 跟踪的文件，不含 MSPM0 SDK）+ 编好的 Windows 仿真板 build/host-sim/*/*.elf.exe
# 用法：bash tools/package_windows.sh [输出目录=/workspace/dist]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUTDIR=${1:-/workspace/dist}
WPY=${WPY:-'C:\py312\python.exe'}
PYVER=3.12.10
VER=$(python3 -c "import json;print(json.load(open('$ROOT/app/src-tauri/tauri.conf.json'))['version'])")
WORK=$(mktemp -d /tmp/dzwin.XXXX)
STAGE="$WORK/电赛工作台"
export WINEDEBUG=-all
mkdir -p "$STAGE" "$OUTDIR"
zpath() { echo "Z:$(echo "$1" | tr / '\\')"; }

echo "== 1/5 仓库子集 + Windows 仿真板"
(cd "$ROOT" && git ls-files -z -- . ':!third_party/mspm0-sdk' | tar --null -cf - -T -) | tar -xf - -C "$WORK" --one-top-level=repo
mv "$WORK/repo" "$STAGE/repo"
APPS=$(cd "$STAGE/repo" && DZBENCH_REPO="$STAGE/repo" python3 -c "import sys;sys.path.insert(0,'app/sidecar');from dzbench.ports import SIM_APPS;print(' '.join(SIM_APPS))")
for a in $APPS; do
  make -s -C "$STAGE/repo" BOARD=host-sim APP="$a" CC=x86_64-w64-mingw32-gcc OS=Windows_NT "LDFLAGS=-lm -lwinmm -static" >/dev/null
  mv "$STAGE/repo/build/host-sim/$a/$a.elf" "$STAGE/repo/build/host-sim/$a/$a.elf.exe"
  rm -rf "$STAGE/repo/build/host-sim/$a/obj"
done
rm -rf "$STAGE/repo/build/host-sim/gen/obj"

echo "== 2/5 侧车 dzbench.exe（wine + PyInstaller）"
(cd "$WORK" && wine "$WPY" -m PyInstaller --noconfirm --onefile --log-level ERROR -n dzbench \
  --distpath "$(zpath "$WORK/pyi")" --workpath "$(zpath "$WORK/pyiw")" --specpath "$(zpath "$WORK")" \
  --add-data "$(zpath "$ROOT/third_party/packs/TexasInstruments.MSPM0G1X0X_G3X0X_DFP.1.3.1.pack");packs" \
  --paths "$(zpath "$ROOT/app/sidecar")" --paths "$(zpath "$ROOT/host/python")" --paths "$(zpath "$ROOT/third_party/vendored/pid_helper")" \
  --hidden-import serial.tools.list_ports "$(zpath "$ROOT/app/sidecar/dzbench_entry.py")")
cp "$WORK/pyi/dzbench.exe" "$STAGE/dzbench.exe"

echo "== 3/5 嵌入版 Python（tools/*.py 用）"
curl -fsSL -o "$WORK/pyemb.zip" "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
mkdir -p "$STAGE/python" && (cd "$STAGE/python" && unzip -q "$WORK/pyemb.zip")
printf 'python312.zip\n.\nLib\\site-packages\nimport site\n' > "$STAGE/python/python312._pth"
wine "$WPY" -m pip install -q --target "$(zpath "$STAGE/python/Lib/site-packages")" pyyaml jsonschema pyserial

echo "== 4/5 Tauri 外壳（x86_64-pc-windows-gnu）"
mkdir -p "$ROOT/app/src-tauri/binaries" && cp "$STAGE/dzbench.exe" "$ROOT/app/src-tauri/binaries/dzbench-x86_64-pc-windows-gnu.exe"
(cd "$ROOT/app/src-tauri" && npx --yes @tauri-apps/cli@2 build --target x86_64-pc-windows-gnu --no-bundle >/dev/null)   # CLI 会开 custom-protocol 并先编前端；裸 cargo build 会去连 devUrl
cp "$ROOT/app/src-tauri/target/x86_64-pc-windows-gnu/release/dzbench.exe" "$STAGE/电赛工作台.exe"
cp "$ROOT/app/src-tauri/target/x86_64-pc-windows-gnu/release/WebView2Loader.dll" "$STAGE/"   # windows-gnu 动态链接它，缺了直接起不来

echo "== 5/5 说明 + zip"
cp "$ROOT/app/packaging/使用说明.txt" "$STAGE/使用说明.txt"
ZIP="$OUTDIR/电赛工作台-$VER-win64-portable.zip"
rm -f "$ZIP"; (cd "$WORK" && zip -qr9 "$ZIP" "电赛工作台")
echo "✓ $ZIP ($(du -h "$ZIP" | cut -f1))"
rm -rf "$WORK"
