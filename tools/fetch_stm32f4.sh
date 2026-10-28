#!/usr/bin/env bash
# 下载 STM32F4 HAL / 器件 CMSIS / CMSIS Core 到 third_party/（只读，永不修改，不提交进仓库）。
# 用于 port: stm32f4-hal，以及 CubeMX 工程未勾选 "Copy all used libraries" 时的 stm32-cubemx。
# 版本固定在 tag，保证可复现；升级时改这里并重跑 make check + 交叉编译。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p third_party && cd third_party
get() {  # get <目录> <仓库> <tag>
  [ -d "$1/.git" ] || [ -d "$1" ] && { echo "已存在 $1，跳过"; return; }
  git clone --depth 1 --branch "$3" "https://github.com/$2.git" "$1"
}
get stm32f4xx-hal-driver STMicroelectronics/stm32f4xx-hal-driver v1.8.5
get cmsis-device-f4      STMicroelectronics/cmsis-device-f4      v2.6.11
if [ ! -d CMSIS_5 ]; then
  git clone --depth 1 --branch 5.9.0 --filter=blob:none --sparse https://github.com/ARM-software/CMSIS_5.git CMSIS_5
  git -C CMSIS_5 sparse-checkout set CMSIS/Core/Include
fi
echo "✓ third_party 就绪"
