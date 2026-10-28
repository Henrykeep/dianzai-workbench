"""内置 Agent（docs/18）。

tuning   —— 离线：阶跃响应指标 + 规则调参建议（不需要 LLM，断网可用）
gateway  —— 工具网关：按层授权、diff 确认、make check 门禁、git 提交/回滚；急停永远不在工具表里
yamlpar  —— 参数写回 yaml（只生成 diff，由网关落地）
llm      —— OpenAI 兼容客户端（OpenAI / DeepSeek / 通义千问 / Kimi / 智谱 / Ollama 本地），密钥只存本机
loop     —— 对话循环：LLM ↔ 网关工具调用，步数上限
"""
