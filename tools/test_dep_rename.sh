#!/usr/bin/env bash
# 增量编译不怕头文件改名/删除（-MMD -MP）：先编一次，把应用里的头文件改名、改 include，不 clean 直接再编。
# 没有 -MP 时旧 .d 里还记着旧头文件 → “No rule to make target …/xxx.h”。
set -euo pipefail
cd "$(dirname "$0")/.."
APP=zz-test-deprename
T=$(mktemp -d)
trap 'rm -rf "$T" build/host-sim/$APP' EXIT
cp -r apps/port_selftest "$T/$APP"
sed -i "s/^name:.*/name: $APP/" "$T/$APP/app.yaml"
printf '#define DEPRENAME_K 1\n' > "$T/$APP/dep_old.h"
sed -i '1i #include "dep_old.h"' "$T/$APP/app_main.c"
make -s BOARD=host-sim APP=$APP APP_DIR="$T/$APP" >/dev/null
mv "$T/$APP/dep_old.h" "$T/$APP/dep_new.h"
sed -i 's/dep_old.h/dep_new.h/' "$T/$APP/app_main.c"
if ! out=$(make -s BOARD=host-sim APP=$APP APP_DIR="$T/$APP" 2>&1); then
  echo "✗ 头文件改名后增量编译失败："; echo "$out" | tail -5; exit 1
fi
echo "✓ dep_rename：头文件改名后不 clean 增量编译通过（-MMD -MP）"
