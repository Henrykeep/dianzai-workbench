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
    n=$(basename "$d"); { [ "$n" = packs ] || [ "$n" = vendored ]; } && continue   # vendored 是提交进仓库的，用克隆里的
    case "$n" in sysconfig_*) ln -s "${d%/}" "$tmp/repo/third_party/$n"; continue;; esac   # SysConfig CLI 1.1G、只读工具：链接不复制
    cp -a "$d" "$tmp/repo/third_party/$n"
  done
fi
# 前端 node_modules（npm ci 装好的工具链，make licenses 的 npm 检查要用）：有就复制，和 CI 的 npm ci 等价
[ -d "$src/app/ui/node_modules" ] && cp -a "$src/app/ui/node_modules" "$tmp/repo/app/ui/node_modules"
for v in $(env | sed -n 's/^\(\(DZBENCH\|PYOCD\)_[A-Z_]*\)=.*/\1/p'); do unset "$v"; done
# 已装的 Python 包（pip --user）是工具链不是“机器状态”，保留；其余 HOME 内容一律看不到
export PYTHONUSERBASE="$(python3 -m site --user-base)"
export HOME="$tmp/home" PYTHONDONTWRITEBYTECODE=1 GIT_CONFIG_NOSYSTEM=1
cd "$tmp/repo"
step() { echo "── preflight: $*"; "$@" >"$tmp/log" 2>&1 || { tail -40 "$tmp/log"; echo "✗ preflight 失败：$*"; exit 1; }; }
step make check            # ci.yml
step make test
step make compat
step make cross            # firmware.yml / cross
echo "✓ preflight 通过（$(git rev-parse --short HEAD)，干净克隆 + 空 HOME + 无器件包）"
