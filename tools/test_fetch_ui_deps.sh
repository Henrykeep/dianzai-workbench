#!/usr/bin/env bash
# #33 回归：node_modules 为软链接 → 失败且链接不动；普通目录 / 不存在 → 照常执行（npm 打桩，无需联网）。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/target"
printf '#!/bin/sh\necho "$@" > "$NPM_LOG"\n' > "$T/bin/npm"; chmod +x "$T/bin/npm"
run() { PATH="$T/bin:$PATH" NPM_LOG="$T/npm.log" DZ_UI_DIR="$T/ui" "$HERE/fetch_ui_deps.sh"; }
fail=0; ok() { echo "ok - $1"; }; ng() { echo "FAIL - $1"; fail=1; }
# 1 软链接
rm -rf "$T/ui" "$T/npm.log"; mkdir -p "$T/ui"; touch "$T/target/keep"; ln -s "$T/target" "$T/ui/node_modules"
if run 2>"$T/err"; then ng "symlink should fail"; else ok "symlink exits non-zero"; fi
[ -L "$T/ui/node_modules" ] && [ "$(readlink "$T/ui/node_modules")" = "$T/target" ] && [ -f "$T/target/keep" ] && ok "link untouched" || ng "link modified"
[ ! -e "$T/npm.log" ] && ok "npm not run" || ng "npm ran"
grep -q "软链接" "$T/err" && grep -q "make fetch" "$T/err" && ok "chinese error with fix" || ng "error message"
# 2 普通目录
rm -rf "$T/ui" "$T/npm.log"; mkdir -p "$T/ui/node_modules"
run && grep -q "^ci " "$T/npm.log" && ok "dir proceeds to npm ci" || ng "dir"
# 3 不存在
rm -rf "$T/ui" "$T/npm.log"; mkdir -p "$T/ui"
run && grep -q "^ci " "$T/npm.log" && ok "missing proceeds to npm ci" || ng "missing"
exit $fail
