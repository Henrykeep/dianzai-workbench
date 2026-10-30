#!/usr/bin/env bash
# 安装包里的 repo\：git 跟踪的文件（不含 MSPM0 SDK）+ mingw 交叉编好的 Windows 仿真板 build/host-sim/*/*.elf.exe
# CI（app-windows.yml 的 win-repo 任务）和 tools/package_windows.sh 共用。用法：bash tools/stage_win_repo.sh <输出目录>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:?输出目录}
rm -rf "$OUT" && mkdir -p "$OUT"
(cd "$ROOT" && git ls-files -z -- . ':!third_party/mspm0-sdk' ':!tools/testdata' ':!docs/assets' | tar --null -cf - -T -) | tar -xf - -C "$OUT"
APPS=$(cd "$OUT" && DZBENCH_REPO="$OUT" python3 -c "import sys;sys.path.insert(0,'app/sidecar');from dzbench.ports import SIM_APPS;print(' '.join(SIM_APPS))")
for a in $APPS; do
  make -s -C "$OUT" BOARD=host-sim APP="$a" CC=x86_64-w64-mingw32-gcc OS=Windows_NT "LDFLAGS=-lm -lwinmm -static" >/dev/null
  mv "$OUT/build/host-sim/$a/$a.elf" "$OUT/build/host-sim/$a/$a.elf.exe"
  x86_64-w64-mingw32-strip "$OUT/build/host-sim/$a/$a.elf.exe"
  rm -rf "$OUT/build/host-sim/$a/obj"
done
rm -rf "$OUT/build/host-sim/gen/obj"
echo "✓ $OUT：仿真板 $APPS（$(du -sh "$OUT" | cut -f1)）"
