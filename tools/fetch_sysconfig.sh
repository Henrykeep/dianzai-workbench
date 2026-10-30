#!/usr/bin/env bash
# 无界面安装 TI SysConfig CLI 1.28.0.4712 到 third_party/sysconfig_1.28.0（不入库；make fetch 会调用）。
# 官方免费下载（dr-download.ti.com，无需登录，CI firmware.yml 也用这个地址）；版本与 sha256 锁定，换版本同时改 VER / SHA。
# MSPM0 从零新建（gen_syscfg.py）与 .syscfg 一致性检查（syscfg_gen.sh）都用它；SYSCFG_CLI 环境变量可覆盖。
set -euo pipefail
cd "$(dirname "$0")/.."
VER=1.28.0.4712; F=sysconfig-1.28.0_4712-setup.run
SHA=222dd65e0c8396e99e4f2839dcf9c2058238e875d85b06869c865a6e21962aee
DEST=$PWD/third_party/sysconfig_1.28.0
[ -x "$DEST/sysconfig_cli.sh" ] && { echo "已存在 $DEST，跳过"; exit 0; }
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
curl -fsSL -o "$t/$F" "https://dr-download.ti.com/software-development/ide-configuration-compiler-or-debugger/MD-nsUM6f7Vvb/$VER/$F"
echo "$SHA  $t/$F" | sha256sum -c - >/dev/null || { echo "✗ $F sha256 不符" >&2; exit 1; }
chmod +x "$t/$F" && "$t/$F" --mode unattended --prefix "$DEST" >/dev/null
[ -x "$DEST/sysconfig_cli.sh" ] && echo "✓ SysConfig CLI $VER → $DEST" || { echo "✗ SysConfig 安装失败" >&2; exit 1; }
