// #62 调参页「自动迭代」（本地服务 #38：agent_tool iterate_start / iterate_cancel；事件 iterate.started / round / stopped）
// 纯状态机 + 文案；main.ts 只做 DOM 接线。预算一律以本地服务报的 limits 为准，没报前按板型兜底（实机 8 轮、仿真 20 轮、180 s）。
export type Limits = { time_s: number; rounds: number };
export const DEFAULT_LIMITS = (sim: boolean): Limits => ({ time_s: 180, rounds: sim ? 20 : 8 });
export type Gap = { value: number; limit: number; gap: number; unit: string };
export type Best = { iter: number; params: Record<string, number>; params_hash?: string; metrics?: Record<string, unknown>; pass?: unknown; gaps?: Record<string, Gap> };
export type Stopped = { reason: string; message_zh?: string; rounds?: number; best?: Best | null; next_zh?: string; best_card?: number | null };
// 本地服务在 iterate.stopped 后推一张 agent_action（tool=iterate_apply_best，“采用最好参数”）：界面只出一张卡——调参页这张，按钮确认的就是那张 action
export const APPLY_TOOL = "iterate_apply_best";
export const APPLY_LABEL = "采用最好参数";
export type IterState =
  | { phase: "idle"; limits: Limits }
  | { phase: "pending"; limits: Limits }               // 实机：等批量确认卡
  | { phase: "running"; limits: Limits; t0: number; iter: number }
  | { phase: "done"; limits: Limits; result: Stopped };
const mmss = (s: number) => { const v = Math.max(0, Math.ceil(s)); return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`; };
export const budgetText = (l: Limits) => `最多 ${l.rounds} 轮 / ${l.time_s} s`;
export const runText = (iter: number, l: Limits, elapsedS: number) => `第 ${Math.min(Math.max(iter, 1), l.rounds)}/${l.rounds} 轮 · 剩余 ${mmss(l.time_s - elapsedS)}`;
export const REASON_ZH: Record<string, string> = {
  autopilot: "自动调参结束", pass: "已连续达标", budget_time: "时间预算用完", budget_rounds: "轮数用完", estop: "急停", stopped: "已手动停止",
  invalid: "连续 3 轮无效", no_improve: "连续 3 轮没有改进", unstable: "出现发散", blocked: "各方向都被挡住", error: "出错",
};
const GAP_ZH: Record<string, string> = { overshoot: "超调", ss_err: "稳态误差", settle: "调节时间", rise: "上升时间" };
const n = (v: number) => String(+(+v).toPrecision(4));
export function gapLines(g: Record<string, Gap> | undefined, pass?: unknown): string[] {
  const ks = Object.keys(g ?? {});
  if (!ks.length) return [pass === true || (pass as any)?.all === true ? "各项指标均已达标" : "这一轮没有完整指标"];
  return ks.map(k => { const x = g![k], u = x.unit === "abs" ? "" : x.unit; return `${GAP_ZH[k] ?? k}：${n(x.value)}${u}，目标 ≤ ${n(x.limit)}${u}，差 ${n(x.gap)}${u}`; });
}
// 稳态误差 vs 任务误差带：本地服务给了带宽才显示（实测值 / 误差带 / 是否在带内 / 来源），不只给“达标”
export type Band = { value: number; band: number; in_band: boolean; unit?: string; source?: string };
export function bandLine(b: any): string {
  const x: Band | null = b?.ss_band?.band != null ? b.ss_band
    : b?.metrics?.band != null && b?.metrics?.ss_err_pct != null
      ? { value: b.metrics.ss_err_pct, band: b.metrics.band, in_band: (b.pass?.ss_err ?? Math.abs(b.metrics.ss_err_pct) <= b.metrics.band) === true, unit: b.metrics.metric_mode === "abs" ? "" : "%", source: "板上阶跃 step_result" }
      : null;
  if (!x) return "";
  const u = x.unit ?? "";
  return `稳态误差 ${n(x.value)}${u} / 任务误差带 ±${n(x.band)}${u} · ${x.in_band ? "在带内" : "超出误差带"}${x.source ? `（来源：${x.source}）` : ""}`;
}
export function cardView(r: Stopped): { title: string; reason: string; params: [string, string][]; gaps: string[]; canWrite: boolean; next: string } {
  const b = r.best ?? null;
  return {
    title: b ? `最好一组参数（第 ${b.iter} 轮）` : "没有可用的一轮",
    reason: `停止原因：${REASON_ZH[r.reason] ?? r.reason}${r.message_zh ? `（${r.message_zh}）` : ""}`,
    params: b ? Object.entries(b.params).map(([k, v]) => [k, n(v)]) : [],
    gaps: b ? [bandLine(b), ...gapLines(b.gaps, b.pass)].filter(Boolean) : [],
    canWrite: !!b && Object.keys(b.params ?? {}).length > 0,
    next: /flash/i.test(r.next_zh ?? "") ? "" : (r.next_zh ?? ""),   // #63：“写入 Flash”只在「保存参数」旁
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
    if (m?.type === "iterate.stopped") { const id = this.s.phase === "done" ? this.s.result.best_card : undefined; this.s = { phase: "done", limits: this.s.limits, result: { ...m, best_card: m.best_card ?? id ?? null } }; return true; }
    if (m?.type === "agent_action" && m.tool === APPLY_TOOL) { this.cardId = m.id; if (this.s.phase === "done") this.s.result.best_card = m.id; return true; }
    return false;
  }
  cardId: number | null = null;
  // 重连 / 刷新：iterate_status {running, result}
  onStatus(r: any, now: number, dismissed?: number | null) {
    if (!r?.running && r?.result && r.result.best_card != null && r.result.best_card === dismissed) return;   // 已采用 / 已收起的结果不再出卡
    if (r?.running) { if (this.s.phase !== "running") this.s = { phase: "running", limits: this.s.limits, t0: now, iter: 0 }; }
    else if (r?.result && this.s.phase !== "done" && r.result.type !== "tune.stopped") this.s = { phase: "done", limits: this.s.limits, result: { ...r.result, best_card: r.result.best_card ?? null } };
    else if (r?.result?.type === "tune.stopped" && this.s.phase !== "done") this.s = { phase: "done", limits: this.s.limits, result: { reason: "autopilot", ...r.result } };
  }
  applyId(): number | null { return this.s.phase === "done" ? (this.s.result.best_card ?? this.cardId) : null; }
  reset() { this.cardId = null; this.s = { phase: "idle", limits: this.s.limits }; }
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
