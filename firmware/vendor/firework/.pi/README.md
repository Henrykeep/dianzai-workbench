# Pi 项目专项增强

这些文件只作用于 `freertos_firework` 仓库，不会修改全局 Pi、Qwen 或 llama-server。

从仓库根目录启动 Pi。首次出现项目资源信任提示时，确认信任当前仓库。若 Pi 会话在这些
文件创建前就已打开，先执行 `/trust` 保存当前仓库信任，重启 Pi；已信任的会话以后修改
项目资源后只需执行 `/reload`。

可用入口：

- `/project-diagnose <问题>`：只读定位原因，不修改代码。
- `/safe-change <需求>`：按项目分层和验证规则完成最小改动。
- `/uart3-audit <命令或场景>`：检查发送、返回解析、状态机、显示和超时全链路。
- `/firmware-review [范围]`：审查当前固件或指定范围的嵌入式风险。
- `/skill:freertos-firework <任务>`：显式加载完整项目专项技能。

快速体检：

```bash
tools/pi_project_check.sh --quick
```

包含完整 Debug 构建：

```bash
tools/pi_project_check.sh --build
```
