"""dzbench —— 电赛工作台桌面端 sidecar：串口/仿真板 ↔ dzframe/dzctl ↔ WebSocket ↔ UI。

模块分工（每个文件只管一件事）：
  transport  串口（pyserial）/ 仿真板（host-sim --stream 子进程）/ 回放
  ports      列串口、自动探测波特率（看有没有合法 dzframe）
  schema     link_schema.json 的查找（按心跳里的哈希）与遥测解码
  session    一次连接：收帧、解码、参数读写（等 ACK、重发）、急停、原始日志
  downsample 给 UI 的 60 fps 抽稀（min/max 保峰值）
  logfile    .dzlog 原始字节日志的写/读
  snapshots  参数快照保存/恢复
  agent_api  给将来内置 Agent 的工具层：只读遥测 + “提议”改参（必须用户确认）
  server     WebSocket JSON 协议（UI 与 Agent 共用）
"""
__version__ = "0.10.0"
