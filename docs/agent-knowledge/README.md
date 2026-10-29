# docs/agent-knowledge —— 内置 Agent 按需加载的知识

- 每篇一个主题，文件头写触发词；用户的话里出现任一触发词（不分大小写）时，这篇正文附在那句话前面给 Agent 看。
  ```
  ---
  triggers: 堵转, stall, 卡死
  ---
  正文……
  ```
- 短而具体：结论、判据、本仓库对应的文件和命令。不要整章抄教材。
- `project-memory.md` 是项目记忆：Agent 用 remember 工具提议、人在 diff 卡上接受后才追加。每次新对话放进系统提示。
- 本目录在网关的 docs 层：Agent 只能提议改，人确认后落地。
