# serialweb —— 网页串口调试与图形解析工作台（原样搬入）

Source: github.com/Conductance-lab/SerialWeb@ff84c5d43dde6b6c49cddc1b7b01f9c55e3ece1a index.html

- 搬了什么：仓库根目录的单文件应用 `index.html`（串口连接管理、文本/HEX 监视、解析规则、时域/频域/柱状图、手动/定时/触发/预设发送、时间线录制回放导出），以及 `README.md`、`AGENTS.md`、`llms.txt`、`skills/html-webserial-app/SKILL.md`、`ai/agent-prompt.md`（上游给 AI 读的开发说明）。原 `LICENSE` 原样保留。
- 没搬：`release/`（历史版本）、`tools/sync-agent-prompt.mjs`（上游维护脚本）。
- 改了什么：无，全部逐字节原样。
- 许可：上游许可见同目录 LICENSE；本仓库整体按 AGPL-3.0-or-later 发布，许可兼容（统筹者 2026-11-04 决定）。
- 接入说明：上游用浏览器 Web Serial 连串口；按定稿，芯台 exe 和网页端碰硬件都只走本机后台程序，所以接入时由前端把它的串口底层换成侧车接口，界面和解析逻辑直接用。接入改动请写在本文件“改了什么”下。
- 冒烟测试：`tools/test_vendored_serialweb.py`（文件逐字节一致、内联脚本可被 node 语法检查）。
