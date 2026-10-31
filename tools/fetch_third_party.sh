#!/usr/bin/env bash
# 下载官方第三方库到 third_party/（只读，永不修改，不提交进仓库；.gitignore 已忽略）。
# 版本固定在 tag，保证可复现；升级时改这里并重跑 make check + 各板交叉编译。
#   tools/fetch_third_party.sh            # 全部
#   tools/fetch_third_party.sh f1 mspm0   # 只要某几组：f4 f1 freertos mspm0 cmsis
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p third_party && cd third_party
get() {  # get <目录> <仓库> <tag> [稀疏检出路径...]
  local dir=$1 repo=$2 tag=$3; shift 3
  if [ -d "$dir" ]; then echo "已存在 $dir，跳过"; return; fi
  if [ $# -gt 0 ]; then
    git clone -c core.autocrlf=false -c core.eol=lf --depth 1 --branch "$tag" --filter=blob:none --sparse "https://github.com/$repo.git" "$dir"
    git -C "$dir" sparse-checkout set "$@"
  else
    git clone -c core.autocrlf=false -c core.eol=lf --depth 1 --branch "$tag" "https://github.com/$repo.git" "$dir"
  fi
}
ALL="${*:-}"
# fetch_url <url> <输出文件> <sha256>：带重试 + sha256 校验，见 tools/fetch_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fetch_lib.sh"
# CMSIS Core（Apache-2.0）：CMSIS_6 固定 tag 的源码包，校验包的 sha256，只解出 CMSIS/Core/Include（+ RTOS2 API 头，FreeRTOS 的
# CMSIS_RTOS_V2 封装要 cmsis_os2.h）和 LICENSE。旧做法（CMSIS_5 稀疏克隆）在新克隆里会缺 core_cm3.h / core_cm4.h。
CMSIS_TAG=v6.1.0
CMSIS_SHA=d8a044e4b50b7112476d6855a12c729ae2b70b3f77a2a038c23890e9a3515973
CMSIS_TREE_SHA=d95d37cc4d996a014a1e62c807222226141c4354b87b70d89813b8a67786e774   # tools/tree_sha256.py（排序 POSIX 路径 + 内容，CRLF→LF，忽略权限位；跨平台一致）
cmsis_verify() {  # 下载后立即校验：缺任何一个头 / 内容不一致 → 失败
  local d=CMSIS_6 h miss=0
  for h in core_cm0plus.h core_cm3.h core_cm4.h core_cm7.h cmsis_compiler.h cmsis_gcc.h cmsis_version.h \
           m-profile/cmsis_gcc_m.h m-profile/armv7m_mpu.h; do
    [ -s "$d/CMSIS/Core/Include/$h" ] || { echo "✗ [fetch/cmsis] 缺 $d/CMSIS/Core/Include/$h · 处理：rm -rf third_party/CMSIS_6 后重跑 make fetch"; miss=1; }
  done
  [ -s "$d/CMSIS/RTOS2/Include/cmsis_os2.h" ] && [ -s "$d/LICENSE" ] || { echo "✗ [fetch/cmsis] 缺 cmsis_os2.h 或 LICENSE"; miss=1; }
  [ $miss = 0 ] || return 1
  local py; py=$(command -v python3 || command -v python)
  local got; got=$("$py" ../tools/tree_sha256.py "$d" CMSIS/Core/Include CMSIS/RTOS2/Include)
  [ "$got" = "$CMSIS_TREE_SHA" ] || { echo "✗ [fetch/cmsis] $d 内容与 $CMSIS_TAG 不一致（$got）· 处理：rm -rf third_party/CMSIS_6 后重跑 make fetch"; return 1; }
  echo "✓ CMSIS_6 $CMSIS_TAG Core/Include 完整（sha256 已校验）"
}
cmsis() {
  if [ ! -d CMSIS_6 ]; then
    local t; t=$(mktemp -d)
    fetch_url "https://codeload.github.com/ARM-software/CMSIS_6/tar.gz/refs/tags/$CMSIS_TAG" "$t/c.tgz" "$CMSIS_SHA" || { echo "✗ [fetch/cmsis] 源码包下载或 sha256 校验失败"; rm -rf "$t"; return 1; }
    local top="CMSIS_6-${CMSIS_TAG#v}"
    tar xzf "$t/c.tgz" -C "$t" "$top/CMSIS/Core/Include" "$top/CMSIS/RTOS2/Include" "$top/LICENSE"
    mkdir -p CMSIS_6.tmp && mv "$t/$top/CMSIS" "$t/$top/LICENSE" CMSIS_6.tmp/ && mv CMSIS_6.tmp CMSIS_6
    rm -rf "$t"
  else
    echo "已存在 CMSIS_6，校验"
  fi
  cmsis_verify
}
f4()       { get stm32f4xx-hal-driver STMicroelectronics/stm32f4xx-hal-driver v1.8.5
             get cmsis-device-f4      STMicroelectronics/cmsis-device-f4      v2.6.11; cmsis; }
f1()       { get stm32f1xx-hal-driver STMicroelectronics/stm32f1xx-hal-driver v1.1.9
             get cmsis-device-f1      STMicroelectronics/cmsis-device-f1      v4.3.5; cmsis; }
# CubeMX 的 FreeRTOS（含 CMSIS_RTOS_V2 封装）。STM32CubeF4 V1.28.x 自带 10.6.2
freertos() { get stm32-mw-freertos STMicroelectronics/stm32-mw-freertos v10.6.2_20241011; }
# TI MSPM0 SDK：只取 DriverLib、器件头/启动文件/链接脚本、CMSIS Core
mspm0()    { get mspm0-sdk TexasInstruments/mspm0-sdk mspm0_sdk_2_11_00_07 .metadata \
               source/ti/driverlib source/ti/devices/msp source/ti/project_config source/third_party/CMSIS/Core/Include; }   # project_config：.syscfg 的 ProjectConfig.genLinker（掉电保存区 .cmd）
# TI MSPM0G1X0X_G3X0X CMSIS 器件包（BSD-3-Clause，pyOCD 烧 MSPM0 要用；随安装包分发，许可证见包内 01_Pack/license.txt）
m0pack()   { mkdir -p packs; local f=packs/TexasInstruments.MSPM0G1X0X_G3X0X_DFP.1.3.1.pack
             [ -f "$f" ] && { echo "已存在 $f，跳过"; return; }
             fetch_url "${M0PACK_URL:-https://software-dl.ti.com/msp430/esd/MSPM0-CMSIS/MSPM0G1X0X_G3X0X/latest/exports/TexasInstruments.MSPM0G1X0X_G3X0X_DFP.1.3.1.pack}" "$f" "$M0PACK_SHA"; }
M0PACK_SHA=071bd317fc0f152ded6b2ae594d79c6fc5eb9952370526b4c14ef5b3b9807860   # 改版本时同步改 workflow 缓存 key
for g in f4 f1 freertos mspm0 m0pack; do
  if [ -z "$ALL" ] || [[ " $ALL " == *" $g "* ]]; then $g; fi
done
if [[ " $ALL " == *" cmsis "* ]]; then cmsis; fi
echo "✓ third_party 就绪"
