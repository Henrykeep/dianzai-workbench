#!/usr/bin/env bash
# make fetch 的前端依赖步骤：app/ui/node_modules 若是软链接则拒绝执行（#33），否则 npm ci。
# 只检查不修改：发现软链接时不删除、不覆盖任何内容。
set -euo pipefail
UI_DIR="${DZ_UI_DIR:-$(cd "$(dirname "$0")/.." && pwd)/app/ui}"
NM="$UI_DIR/node_modules"
if [ -L "$NM" ]; then
  echo "错误：$NM 是软链接（指向 $(readlink "$NM")）。" >&2
  echo "原因：每个 worktree 必须有独立的 node_modules；npm ci 会清空链接目标，误删其他 worktree 的依赖。" >&2
  echo "修复：rm \"$NM\"（只删链接本身，勿加 -r），然后重新执行 make fetch。" >&2
  exit 3
fi
cd "$UI_DIR" && npm ci --no-audit --no-fund
