#!/usr/bin/env bash
# 用 TI SysConfig CLI 从 .syscfg 重新生成 ti_msp_dl_config.{c,h}，并与入库版本比对。
#   tools/syscfg_gen.sh [板]            # 比对（CI 用；不一致返回 1）；板默认 mspm0g3507-tianmengxing
#   tools/syscfg_gen.sh [板] --write    # 覆盖入库文件
# 环境变量：SYSCFG_CLI（默认 ~/ti/sysconfig_1.28.0/sysconfig_cli.sh）、M0_SDK_ROOT（默认 third_party/mspm0-sdk）
# 版本锁：SysConfig 1.28.0.4712 + MSPM0 SDK 2.11.00.07。换版本后生成文件的注释/默认值可能变，需重新 --write 并审阅 diff。
set -euo pipefail
CLI=${SYSCFG_CLI:-$HOME/ti/sysconfig_1.28.0/sysconfig_cli.sh}
SDK=${M0_SDK_ROOT:-third_party/mspm0-sdk}
case "${1:-}" in ""|--*) ;; *) B=$1; shift;; esac
BOARD=boards/${B:-mspm0g3507-tianmengxing}
SC=$(ls "$BOARD"/ccs/*.syscfg | head -1)
[ -x "$CLI" ] || { echo "找不到 SysConfig CLI：$CLI（设置 SYSCFG_CLI）"; exit 2; }
[ -f "$SDK/.metadata/product.json" ] || { echo "SDK 缺 .metadata/product.json：tools/fetch_third_party.sh mspm0"; exit 2; }
out=$(mktemp -d)
"$CLI" --product "$SDK/.metadata/product.json" --device MSPM0G350X --package "LQFP-64(PM)" \
       -o "$out" "$SC" 2>&1 | grep -v "^Ignoring the following missing components" || true
[ -f "$out/ti_msp_dl_config.h" ] || { echo "✗ SysConfig 生成失败"; exit 1; }
if [ "${1:-}" = "--write" ]; then cp "$out"/ti_msp_dl_config.[ch] "$BOARD/syscfg/"; echo "✓ 已写入 $BOARD/syscfg/"; exit 0; fi
diff -u "$BOARD/syscfg/ti_msp_dl_config.h" "$out/ti_msp_dl_config.h" && diff -u "$BOARD/syscfg/ti_msp_dl_config.c" "$out/ti_msp_dl_config.c" \
  && echo "✓ ti_msp_dl_config 与 .syscfg 一致" || { echo "✗ 入库的 ti_msp_dl_config 与 .syscfg 不一致：tools/syscfg_gen.sh --write"; exit 1; }
