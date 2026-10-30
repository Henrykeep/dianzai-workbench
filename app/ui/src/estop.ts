// 急停来源：枚举 + 兜底文案。正式文案由侧车在事件里给（detail / fix），前端只显示侧车给的说明。
// 固件上报来源（source）后，侧车填 detail；侧车未给 detail 时才用这里的兜底。
export type EstopSource = "manual" | "heartbeat_timeout" | "stall" | "undervoltage" | "unknown";
export const ESTOP_FALLBACK: Record<EstopSource, { detail: string; fix: string }> = {
  manual:            { detail: "手动急停", fix: "确认安全后点「解除」" },
  heartbeat_timeout: { detail: "心跳超时（上位机未按时发送数据）", fix: "检查串口连接后点「解除」" },
  stall:             { detail: "堵转", fix: "排除机械卡滞后点「解除」" },
  undervoltage:      { detail: "欠压", fix: "更换或充电电池后点「解除」" },
  unknown:           { detail: "", fix: "排除原因后点「解除」" },
};
// 输出格式：「急停：<detail>。<fix>」；来源未知：「急停已触发（来源未知）。<fix>」
export function estopText(e: { source?: string; detail?: string; fix?: string; kind?: string }): string {
  const src = (e.source && e.source in ESTOP_FALLBACK ? e.source : e.kind === "watchdog" ? "heartbeat_timeout" : "unknown") as EstopSource;
  const fb = ESTOP_FALLBACK[src];
  const detail = e.detail || fb.detail, fix = e.fix || fb.fix;
  return detail ? `急停：${detail}。${fix}` : `急停已触发（来源未知）。${fix}`;
}
