#!/usr/bin/env bash
# 推送前本地跑一遍 CI 的同款步骤，环境尽量干净：
#   * 从当前 HEAD 新克隆到临时目录（未提交的改动不算 —— 和 CI 一样只看提交）
#   * HOME / DZBENCH_HOME 指到空目录（没有 ~/.dzbench 里的包、配置、快照）
#   * third_party/packs（TI 器件包）不带；SDK 源码从本机 third_party 复制以省下载（CI 的 cross 也是下载同版本）
#   * 不继承 DZBENCH_* / PYOCD_* 环境变量
# 用法：make preflight   （PREFLIGHT_KEEP=1 保留临时目录）
set -euo pipefail
src=$(git rev-parse --show-toplevel)
tmp=$(mktemp -d /tmp/dz-preflight.XXXXXX)
trap '[ -n "${PREFLIGHT_KEEP:-}" ] || rm -rf "$tmp"' EXIT
git clone -q --no-hardlinks "$src" "$tmp/repo"
git -C "$tmp/repo" checkout -q "$(git -C "$src" rev-parse HEAD)"
mkdir -p "$tmp/home" "$tmp/repo/third_party"
if [ -d "$src/third_party" ]; then
  for d in "$src"/third_party/*/; do
    n=$(basename "$d"); [ "$n" = packs ] && continue
    cp -a "$d" "$tmp/repo/third_party/$n"
  done
fi
for v in $(env | sed -n 's/^\(\(DZBENCH\|PYOCD\)_[A-Z_]*\)=.*/\1/p'); do unset "$v"; done
export HOME="$tmp/home" PYTHONDONTWRITEBYTECODE=1
cd "$tmp/repo"
step() { echo "── preflight: $*"; "$@" >"$tmp/log" 2>&1 || { tail -40 "$tmp/log"; echo "✗ preflight 失败：$*"; exit 1; }; }
step make check            # ci.yml
step make test
step make compat
step make cross            # firmware.yml / cross
echo "✓ preflight 通过（$(git rev-parse --short HEAD)，干净克隆 + 空 HOME + 无器件包）"
