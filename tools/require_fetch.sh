#!/usr/bin/env bash
# make check / make test 的前置检查：第三方 SDK 没拉（新克隆 / worktree 忘了 make fetch）时，
# 直接给一句可执行的提示并退出非零，而不是跑到后面才在编译里报一堆找不到头文件。
# 用法：tools/require_fetch.sh [仓库根，默认当前目录]   |   tools/require_fetch.sh --selftest
set -u
MSG="缺少 third_party/CMSIS_6，请先运行 make fetch"
check() {   # $1 = 仓库根
  [ -d "$1/third_party/CMSIS_6" ] || { echo "$MSG" >&2; return 1; }
}
if [ "${1:-}" = "--selftest" ]; then
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  out=$(check "$t" 2>&1); rc=$?
  [ $rc -ne 0 ] && [ "$out" = "$MSG" ] || { echo "✗ require_fetch 自测：缺 CMSIS_6 应退出非零并只打印「$MSG」（rc=$rc out=$out）"; exit 1; }
  mkdir -p "$t/third_party/CMSIS_6"
  out=$(check "$t" 2>&1) && [ -z "$out" ] || { echo "✗ require_fetch 自测：有 CMSIS_6 时应静默通过（out=$out）"; exit 1; }
  echo "✓ require_fetch 自测通过"; exit 0
fi
check "${1:-.}"
