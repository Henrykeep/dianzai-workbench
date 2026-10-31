// r8 预检修复（纯函数，main.ts / analysis.ts / progress.ts 接线）
import type { Ev } from "./timeline";
// 1 解除时往时间线追加一条中性「急停已解除」（kind estop_clear，灰色），让最新事件不再停在「急停，板子已锁存」
export const CLEARED_EV_TEXT = "急停已解除";
export function clearedEvent(have: { i: number }[], logT: number | null, plotT: number | null): Ev {
  const top = have.reduce((m, e) => Math.max(m, e.i), 0);
  return { i: top + 0.5, kind: "estop_clear", text: CLEARED_EV_TEXT, log_t: logT, plot_t: plotT };
}
// 2 锁存时「解除急停」只在红条与顶栏两处；其它地方（Agent 卡、页头提示、左侧导航）只留文字
export const CLEAR_ONLY_AT = new Set(["estop_clear"]);
export const CLEAR_WHERE = "在红条或顶栏点「解除急停」";
// 3 解除后灰条与右下提示合成一句、一个动作
export const CLEARED_MSG = "设定值已清零，重新开始实验即可";
export const CLEARED_ACT = { label: "重新开始实验", action: "step_test" } as const;   // 阶跃实验（ag-step → tune_step_test），不是自整定
// 4 解除后调参页大字：新阶跃结果到之前一律「—（需重新实验）」
export const STALE_V = "—（需重新实验）";
export class StaleReads {
  private t0: number | null | undefined = undefined;
  clear(t0: number | null) { this.t0 = t0; }
  // 当前 t0 还是解除时那一个 → 仍是旧数据
  stale(t0: number | null): boolean {
    if (this.t0 === undefined) return false;
    if (t0 !== this.t0) { this.t0 = undefined; return false; }
    return true;
  }
}
// 5 复用已连接会话：下拉框显示实际连着的端口（与底栏一致）
export type PortOpt = { port: string; desc: string; kind: string; likely: boolean };
export function portsWithSession(ports: PortOpt[], st: { connected?: boolean; port?: string } | undefined): { ports: PortOpt[]; value: string | null } {
  if (!st?.connected || !st.port) return { ports, value: null };
  if (ports.some(p => p.port === st.port)) return { ports, value: st.port };
  const sim = st.port.startsWith("sim:");
  return { ports: [{ port: st.port, desc: sim ? `仿真板 ${st.port.slice(4)}` : "当前连接", kind: sim ? "sim" : "serial", likely: !sim }, ...ports], value: st.port };
}
// 6 连上时板子已锁存：横幅写明原因；null / 空 → 「原因未知（重连后未上报）」
const blank = (v: unknown) => v == null || (typeof v === "string" && (!v.trim() || /^(null|undefined|none)$/i.test(v.trim())));
export function latchCauseText(c: { cause_zh?: string | null; message_zh?: string | null; cause?: string | null } | null | undefined): string {
  if (c && !blank(c.cause_zh)) return String(c.cause_zh);
  if (c && !blank(c.message_zh)) return String(c.message_zh).replace(/\s*R\s*$/, "").trim();
  return "原因未知（重连后未上报）";
}
export const latchHead = (c: Parameters<typeof latchCauseText>[0]) => `急停已锁存：${latchCauseText(c)}`;
// 顶栏「解除」(#cmd-r) 只在急停锁存时出现；解除后隐藏
export const clearBtnHidden = (latched: boolean) => !latched;
