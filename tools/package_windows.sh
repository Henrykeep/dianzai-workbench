#!/usr/bin/env bash
# 在 Linux 上交叉打 Windows 便携包（GitHub Actions 不可用时的替代；正式发布仍走 .github/workflows/app-windows.yml）
# 依赖：mingw-w64、wine（装好 Windows Python 3.12 到 C:\py312，并 pip 装 requirements + pyinstaller）、
#       rustup target x86_64-pc-windows-gnu、node/npm、zip、curl
# 产物：dist/XinTai-<版本>-win64-portable.zip
#   XinTai.exe        Tauri 外壳（windows-gnu）
#   dzbench.exe            侧车（PyInstaller，wine 里打）
#   repo/                  tools/stage_win_repo.sh 出的工程仓库子集 + Windows 仿真板
#   （tools/*.py 由 dzbench.exe 在本进程里跑，不再带嵌入版 Python）
# 首选是 CI：.github/workflows/app-windows.yml 出 NSIS 安装包；这个脚本只是 CI 不可用时的备用
# 用法：bash tools/package_windows.sh [输出目录=/workspace/dist]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUTDIR=${1:-/workspace/dist}
WPY=${WPY:-'C:\py312\python.exe'}
PYVER=3.12.10
VER=$(python3 -c "import json;print(json.load(open('$ROOT/app/src-tauri/tauri.conf.json'))['version'])")
WORK=$(mktemp -d /tmp/dzwin.XXXX)
STAGE="$WORK/XinTai"
export WINEDEBUG=-all
mkdir -p "$STAGE" "$OUTDIR"
zpath() { echo "Z:$(echo "$1" | tr / '\\')"; }

echo "== 1/5 仓库子集 + Windows 仿真板"
bash "$ROOT/tools/stage_win_repo.sh" "$STAGE/repo"

echo "== 2/5 侧车 dzbench.exe（wine + PyInstaller）"
(cd "$WORK" && wine "$WPY" -m PyInstaller --noconfirm --onefile --log-level ERROR -n dzbench \
  --distpath "$(zpath "$WORK/pyi")" --workpath "$(zpath "$WORK/pyiw")" --specpath "$(zpath "$WORK")" \
  --add-data "$(zpath "$ROOT/third_party/packs/TexasInstruments.MSPM0G1X0X_G3X0X_DFP.1.3.1.pack");packs" \
  --paths "$(zpath "$ROOT/app/sidecar")" --paths "$(zpath "$ROOT/host/python")" --paths "$(zpath "$ROOT/third_party/vendored/stm32_mcp_discovery")" \
  --hidden-import serial.tools.list_ports --collect-submodules pypdf "$(zpath "$ROOT/app/sidecar/dzbench_entry.py")")
cp "$WORK/pyi/dzbench.exe" "$STAGE/dzbench.exe"

echo "== 4/5 Tauri 外壳（x86_64-pc-windows-gnu）"
mkdir -p "$ROOT/app/src-tauri/binaries" && cp "$STAGE/dzbench.exe" "$ROOT/app/src-tauri/binaries/dzbench-x86_64-pc-windows-gnu.exe"
(cd "$ROOT/app/src-tauri" && npx --yes @tauri-apps/cli@2 build --target x86_64-pc-windows-gnu --no-bundle >/dev/null)   # CLI 会开 custom-protocol 并先编前端；裸 cargo build 会去连 devUrl
# 外壳二进制名来自 tauri.conf.json 的 mainBinaryName（dianzai-workbench.exe，CI 日志 "Built application at …\\dianzai-workbench.exe" 可证）；
# 同目录的 release/dzbench.exe 是 externalBin 复制过去的侧车，不是外壳——以前拷错成它，zip 里的“外壳”其实是侧车
REL="$ROOT/app/src-tauri/target/x86_64-pc-windows-gnu/release"
SHELL_BIN=$(python3 -c "import json;c=json.load(open('$ROOT/app/src-tauri/tauri.conf.json'));print(c.get('mainBinaryName') or c['productName'])").exe
[ -f "$REL/$SHELL_BIN" ] || { echo "✗ 找不到 Tauri 外壳 $REL/$SHELL_BIN（tauri build 没产出？看上一步输出 / tauri.conf.json mainBinaryName）" >&2; ls -la "$REL" >&2 || true; exit 1; }
cp "$REL/$SHELL_BIN" "$STAGE/XinTai.exe"
cp "$REL/WebView2Loader.dll" "$STAGE/"   # windows-gnu 动态链接它，缺了直接起不来

echo "== 5/5 说明 + zip"
cp "$ROOT/app/packaging/使用说明.txt" "$STAGE/README-zh.txt"
ZIP="$OUTDIR/XinTai-$VER-win64-portable.zip"
for f in XinTai.exe dzbench.exe WebView2Loader.dll; do [ -s "$STAGE/$f" ] || { echo "✗ 便携包缺 $f，不出 zip" >&2; exit 1; }; done
rm -f "$ZIP"; (cd "$WORK" && zip -qr9 "$ZIP" "XinTai")
echo "✓ $ZIP ($(du -h "$ZIP" | cut -f1))"
rm -rf "$WORK"
