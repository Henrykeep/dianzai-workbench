#!/usr/bin/env bash

set -u

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_root=$(CDPATH= cd -- "${script_dir}/.." && pwd)
mode=${1:---quick}
failed=0

usage() {
    echo "用法: tools/pi_project_check.sh [--quick|--build]"
}

pass() {
    echo "PASS: $1"
}

fail() {
    echo "FAIL: $1" >&2
    failed=1
}

case "${mode}" in
    --quick|--build)
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

cd "${project_root}" || exit 1

# CCS Theia 会把一串 SDK 文件路径写入该变量指定的 ripgrep 配置文件。
# 项目体检只搜索当前仓库，显式关闭这份外部配置。
export RIPGREP_CONFIG_PATH=/dev/null

required_files=(
    "AGENTS.md"
    ".pi/prompts/project-diagnose.md"
    ".pi/prompts/safe-change.md"
    ".pi/prompts/uart3-audit.md"
    ".pi/prompts/firmware-review.md"
    ".pi/skills/freertos-firework/SKILL.md"
    ".pi/skills/freertos-firework/references/architecture.md"
    ".pi/skills/freertos-firework/references/uart3-protocol.md"
    ".pi/skills/freertos-firework/references/verification.md"
    "application/app_config.h"
    "application/application.c"
    "application/communication/serial_communication/serial_communication.c"
    "application/menu/display_menu/display_menu.c"
)

project_context_files=(
    "AGENTS.md"
    ".pi/README.md"
    ".pi/prompts/project-diagnose.md"
    ".pi/prompts/safe-change.md"
    ".pi/prompts/uart3-audit.md"
    ".pi/prompts/firmware-review.md"
    ".pi/skills/freertos-firework/SKILL.md"
    ".pi/skills/freertos-firework/references/architecture.md"
    ".pi/skills/freertos-firework/references/uart3-protocol.md"
    ".pi/skills/freertos-firework/references/verification.md"
    "tools/pi_project_check.sh"
)

for required_file in "${required_files[@]}"; do
    if [[ ! -f "${required_file}" ]]; then
        fail "缺少 ${required_file}"
    fi
done
if [[ ${failed} -eq 0 ]]; then
    pass "项目上下文、技能、模板和核心源码齐全"
fi

if rg -q -e '^name: freertos-firework$' \
        .pi/skills/freertos-firework/SKILL.md &&
   rg -q -e '^description: .+' \
        .pi/skills/freertos-firework/SKILL.md; then
    pass "freertos-firework 技能 frontmatter 可识别"
else
    fail "freertos-firework 技能缺少 name 或 description"
fi

if rg -q -e 'SerialCommunicationUART3RequestPreparedData' \
        application/communication/serial_communication/serial_communication.c &&
   rg -q -e 'SerialCommunicationUART3GetTransactionStatus' \
        application/menu/display_menu/display_menu.c; then
    pass "UART3 准备事务和页面状态链路存在"
else
    fail "UART3 核心事务符号不完整"
fi

if git diff --check; then
    pass "git diff --check"
else
    fail "git diff 存在空白错误"
fi

if rg -n -e '[[:blank:]]+$' "${project_context_files[@]}"; then
    fail "项目专项增强文件存在行尾空白"
else
    pass "项目专项增强文件无行尾空白"
fi

if [[ -f tools/uart3_host_simulator/server.py ]]; then
    if python3 -c 'from pathlib import Path; p=Path("tools/uart3_host_simulator/server.py"); compile(p.read_text(encoding="utf-8"), str(p), "exec")'; then
        pass "UART3 模拟器 Python 语法"
    else
        fail "UART3 模拟器 Python 语法"
    fi
fi

if [[ -f tools/uart3_host_simulator/launch.sh ]]; then
    if bash -n tools/uart3_host_simulator/launch.sh; then
        pass "UART3 模拟器启动脚本语法"
    else
        fail "UART3 模拟器启动脚本语法"
    fi
fi

if [[ "${mode}" == "--build" ]]; then
    if [[ ! -f Debug/makefile ]]; then
        fail "缺少 CCS 生成的 Debug/makefile"
    elif make -C Debug -j2 all; then
        pass "Debug 固件构建"
    else
        fail "Debug 固件构建"
    fi
fi

echo "INFO: 当前未提交项如下（体检不会修改或清理它们）："
git status --short

if [[ ${failed} -ne 0 ]]; then
    exit 1
fi

echo "项目体检完成。"
