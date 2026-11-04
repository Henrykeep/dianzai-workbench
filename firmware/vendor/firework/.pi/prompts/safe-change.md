---
description: 安全修改当前 FreeRTOS 下位机项目并完成验证
argument-hint: "<修改需求>"
---

请在当前 `freertos_firework` 下位机仓库完成以下需求：$@

先加载 `freertos-firework` 项目技能，检查未提交改动并定位最小修改层。保留用户已有改动，
遵守 BSP/Module/Application 分层、静态任务和异步状态机约束。实施后运行与风险相称的
检查，至少执行 `git diff --check` 和 `tools/pi_project_check.sh --quick`；修改 C 源码时执行
`make -C Debug -j2 all`。最后用中文说明结果、文件、验证和仍需实板确认的事项。
