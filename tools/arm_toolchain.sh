#!/usr/bin/env bash
# 锁定 Arm GNU Toolchain 13.3.rel1（arm-none-eabi-gcc 13.3.1）：本机、preflight、CI 用同一个版本。
#   tools/arm_toolchain.sh --bin        # 打印工具链 bin 目录（带结尾 /），版本不对返回 1
#   tools/arm_toolchain.sh --check      # 打印用的哪个 gcc 和版本；不对就报错退出
#   tools/arm_toolchain.sh --install    # 下载官方 tarball、校验 sha256，解压到 $ARM_TOOLCHAIN_ROOT（默认 /opt/arm）（CI 用）
# 查找顺序：$ARM_TOOLCHAIN_DIR → $ARM_TOOLCHAIN_ROOT/arm-gnu-toolchain-13.3.rel1-x86_64-arm-none-eabi/bin → PATH 上的 arm-none-eabi-gcc
# 换版本：同时改 VER / WANT / SHA，重跑 make cross 并审阅。
set -euo pipefail
VER=13.3.rel1; WANT=13.3.1
NAME=arm-gnu-toolchain-$VER-x86_64-arm-none-eabi
SHA=95c011cee430e64dd6087c75c800f04b9c49832cc1000127a92a97f9c8d83af4
URL=https://developer.arm.com/-/media/Files/downloads/gnu/$VER/binrel/$NAME.tar.xz
ROOT=${ARM_TOOLCHAIN_ROOT:-/opt/arm}

find_bin() {
  for d in "${ARM_TOOLCHAIN_DIR:-}" "$ROOT/$NAME/bin"; do
    [ -n "$d" ] && [ -x "$d/arm-none-eabi-gcc" ] && { echo "${d%/}/"; return; }
  done
  local g; g=$(command -v arm-none-eabi-gcc || true)
  [ -n "$g" ] && echo "$(dirname "$g")/"
}

case "${1:---check}" in
  --install)
    [ -x "$ROOT/$NAME/bin/arm-none-eabi-gcc" ] && { echo "已有 $ROOT/$NAME"; exit 0; }
    t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
    curl -fsSL -o "$t/tc.tar.xz" "$URL"
    echo "$SHA  $t/tc.tar.xz" | sha256sum -c - >/dev/null || { echo "✗ $NAME.tar.xz sha256 不符" >&2; exit 1; }
    mkdir -p "$ROOT" && tar -xJf "$t/tc.tar.xz" -C "$ROOT"
    echo "✓ 已安装 $ROOT/$NAME" ;;
  --bin|--check)
    b=$(find_bin)
    [ -n "$b" ] || { echo "✗ 找不到 arm-none-eabi-gcc：装 Arm GNU Toolchain $VER 到 $ROOT/$NAME（tools/arm_toolchain.sh --install）或设 ARM_TOOLCHAIN_DIR" >&2; exit 1; }
    v=$("${b}arm-none-eabi-gcc" -dumpversion)
    [ "$v" = "$WANT" ] || { echo "✗ arm-none-eabi-gcc 版本不符：${b}arm-none-eabi-gcc 是 $v，锁定的是 $WANT（Arm GNU Toolchain $VER）。tools/arm_toolchain.sh --install，或设 ARM_TOOLCHAIN_DIR 指向 $VER 的 bin" >&2; exit 1; }
    if [ "$1" = --bin ]; then echo "$b"; else echo "arm-none-eabi-gcc $v（Arm GNU Toolchain $VER）：${b}arm-none-eabi-gcc"; fi ;;
  *) sed -n 2,7p "$0"; exit 2 ;;
esac
