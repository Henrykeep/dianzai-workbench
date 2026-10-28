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
    git clone --depth 1 --branch "$tag" --filter=blob:none --sparse "https://github.com/$repo.git" "$dir"
    git -C "$dir" sparse-checkout set "$@"
  else
    git clone --depth 1 --branch "$tag" "https://github.com/$repo.git" "$dir"
  fi
}
ALL="${*:-}"
cmsis()    { get CMSIS_5 ARM-software/CMSIS_5 5.9.0 CMSIS/Core/Include CMSIS/RTOS2/Include; }
f4()       { get stm32f4xx-hal-driver STMicroelectronics/stm32f4xx-hal-driver v1.8.5
             get cmsis-device-f4      STMicroelectronics/cmsis-device-f4      v2.6.11; cmsis; }
f1()       { get stm32f1xx-hal-driver STMicroelectronics/stm32f1xx-hal-driver v1.1.9
             get cmsis-device-f1      STMicroelectronics/cmsis-device-f1      v4.3.5; cmsis; }
# CubeMX 的 FreeRTOS（含 CMSIS_RTOS_V2 封装）。STM32CubeF4 V1.28.x 自带 10.6.2
freertos() { get stm32-mw-freertos STMicroelectronics/stm32-mw-freertos v10.6.2_20241011; }
# TI MSPM0 SDK：只取 DriverLib、器件头/启动文件/链接脚本、CMSIS Core
mspm0()    { get mspm0-sdk TexasInstruments/mspm0-sdk mspm0_sdk_2_11_00_07 .metadata \
               source/ti/driverlib source/ti/devices/msp source/third_party/CMSIS/Core/Include; }
for g in f4 f1 freertos mspm0; do
  if [ -z "$ALL" ] || [[ " $ALL " == *" $g "* ]]; then $g; fi
done
[[ " $ALL " == *" cmsis "* ]] && cmsis
echo "✓ third_party 就绪"
