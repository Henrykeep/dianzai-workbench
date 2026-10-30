// link.state 的 reason → 横幅文案；以及“重连后板子保持待机”的前端状态模型。
// 硬规矩：重连后界面不自动重发任何运动指令/目标值/参数；运行态只认板子上报，断线即视为未知，重连后默认待机。
export type LinkMsg = { board?: string; reason?: string; stale_after_ms?: number };
export type LinkView = { text: string; tone: "neutral" | "warn" | ""; portAttn: boolean };
export function linkView(m: LinkMsg): LinkView {
  if (m.board === "lost" && m.reason === "resuming") return { text: "连接中断，正在重连…", tone: "neutral", portAttn: false };
  if (m.board === "disconnected" && m.reason === "port_not_found") return { text: "未找到上次使用的板子。请检查 USB 连接后点「连接」。", tone: "warn", portAttn: false };
  if (m.board === "disconnected" && m.reason === "port_ambiguous") return { text: "检测到多块同型号的板子，请选择要连接的端口。", tone: "warn", portAttn: true };
  return { text: "", tone: "", portAttn: false };
}
export type Run = "standby" | "running";
let run: Run = "standby";
export const runState = {
  get: () => run,
  // 只有板子上报（status.run / status.mode）能把状态改成运行中
  fromBoard(s: { run?: unknown; mode?: unknown }) { if (s.run != null) run = s.run === true || s.run === "running" ? "running" : "standby"; },
  // 板子不在线：清掉断线前的“运行中”，不缓存任何待重发的指令
  onLink(board: string | undefined) { if (board !== "connected") run = "standby"; },
};
