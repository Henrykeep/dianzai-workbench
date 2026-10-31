// #62 调参页「自动迭代」（本地服务 #38：agent_tool iterate_start / iterate_cancel；事件 iterate.started / round / stopped）
// 纯状态机 + 文案；main.ts 只做 DOM 接线。预算一律以本地服务报的 limits 为准，没报前按板型兜底（实机 8 轮、仿真 20 轮、180 s）。
export type Limits = { time_s: number; rounds: number };
export const DEFAULT_LIMITS = (sim: boolean): Limits => ({ time_s: 180, rounds: sim ? 20 : 8 });
export type Gap = { value: number; limit: number; gap: number; unit: string };
export type Best = { iter: number; params: Record<string, number>; params_hash?: string; metrics?: Record<string, unknown>; pass?: unknown; gaps?: Record<string, Gap> };
export type Stopped = { reason: string; message_zh?: string; rounds?: number; best?: Best | null; next_zh?: string };
export type IterState =
  | { phase: "idle"; limits: Limits }
  | { phase: "pending"; limits: Limits }               // 实机：等批量确认卡
  | { phase: "running"; limits: Limits; t0: number; iter: number }
  | { phase: "done"; limits: Limits; result: Stopped };
const mmss = (s: number) => { const v = Math.max(0, Math.ceil(s)); return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`; };
export const budgetText = (l: Limits) => `最多 ${l.rounds} 轮 / ${l.time_s} s`;
export const runText = (iter: number, l: Limits, elapsedS: number) => `第 ${Math.min(Math.max(iter, 1), l.rounds)}/${l.rounds} 轮 · 剩余 ${mmss(l.time_s - elapsedS)}`;
export const REASON_ZH: Record<string, string> = {
  pass: "已连续达标", budget_time: "时间预算用完", budget_rounds: "轮数用完", estop: "急停", stopped: "已手动停止",
  invalid: "连续 3 轮无效", no_improve: "连续 3 轮没有改进", unstable: "出现发散", blocked: "各方向都被挡住", error: "出错",
};
const GAP_ZH: Record<string, string> = { overshoot: "超调", ss_err: "稳态误差", settle: "调节时间", rise: "上升时间" };
const n = (v: number) => String(+(+v).toPrecision(4));
export function gapLines(g: Record<string, Gap> | undefined, pass?: unknown): string[] {
  const ks = Object.keys(g ?? {});
  if (!ks.length) return [pass === true || (pass as any)?.all === true ? "各项指标均已达标" : "这一轮没有完整指标"];
  return ks.map(k => { const x = g![k], u = x.unit === "abs" ? "" : x.unit; return `${GAP_ZH[k] ?? k}：${n(x.value)}${u}，目标 ≤ ${n(x.limit)}${u}，差 ${n(x.gap)}${u}`; });
}
export function cardView(r: Stopped): { title: string; reason: string; params: [string, string][]; gaps: string[]; canWrite: boolean; next: string } {
  const b = r.best ?? null;
  return {
    title: b ? `最好一组参数（第 ${b.iter} 轮）` : "没有可用的一轮",
    reason: `停止原因：${REASON_ZH[r.reason] ?? r.reason}${r.message_zh ? `（${r.message_zh}）` : ""}`,
    params: b ? Object.entries(b.params).map(([k, v]) => [k, n(v)]) : [],
    gaps: b ? gapLines(b.gaps, b.pass) : [],
    canWrite: !!b && Object.keys(b.params).length > 0,
    next: r.next_zh ?? "",
  };
}
export class IterModel {
  s: IterState;
  constructor(sim = true) { this.s = { phase: "idle", limits: DEFAULT_LIMITS(sim) }; }
  setSim(sim: boolean) { if (this.s.phase === "idle") this.s = { phase: "idle", limits: DEFAULT_LIMITS(sim) }; }
  // iterate_start 回包：{status:"started", budget:{time_s, rounds}} 或 {status:"pending_human_click"}
  onStartReply(r: any, now: number) {
    const b = r?.budget; const l = b && b.rounds ? { time_s: b.time_s, rounds: b.rounds } : this.s.limits;
    if (r?.status === "pending_human_click") this.s = { phase: "pending", limits: l };
    else if (this.s.phase !== "running" && this.s.phase !== "done") this.s = { phase: "running", limits: l, t0: now, iter: 0 };
    else this.s = { ...this.s, limits: l } as IterState;
  }
  onEvent(m: any, now: number): boolean {
    if (m?.type === "iterate.started") { const l = m.limits?.rounds ? { time_s: m.limits.time_s, rounds: m.limits.rounds } : this.s.limits; this.s = { phase: "running", limits: l, t0: now, iter: 0 }; return true; }
    if (m?.type === "iterate.round") { if (this.s.phase !== "running") this.s = { phase: "running", limits: this.s.limits, t0: now, iter: 0 }; (this.s as any).iter = Math.max((this.s as any).iter, +m.iter || 0); return true; }
    if (m?.type === "iterate.stopped") { this.s = { phase: "done", limits: this.s.limits, result: m }; return true; }
    return false;
  }
  reset() { this.s = { phase: "idle", limits: this.s.limits }; }
  // 主按钮（同一位置只一个主按钮）：idle/done → 自动迭代；running/pending → 停止迭代
  button(): { label: string; op: "start" | "cancel" } { return this.s.phase === "running" || this.s.phase === "pending" ? { label: "停止迭代", op: "cancel" } : { label: "自动迭代", op: "start" }; }
  text(now: number): string {
    const s = this.s;
    if (s.phase === "running") return runText(s.iter + 1, s.limits, (now - s.t0) / 1000);
    if (s.phase === "pending") return `等待确认卡 · ${budgetText(s.limits)}`;
    return budgetText(s.limits);
  }
}
// 迭代目标：用最近一次的设定值（非 0）；没有就提示先做一次阶跃实验
export const iterTarget = (sp: { v: number } | null | undefined): number | null => sp && Number.isFinite(sp.v) && sp.v !== 0 ? sp.v : null;
