import { coarseTagHtml } from "./plant";
import { LEDGER, bestValid, fromRoundEvent, type LedgerRound } from "./ledgerbus";
import { pickStr, RESULT_PORT_F, RESULT_CLEAR_EV } from "./fieldmap";
import { toCompare, METRIC_ZH, type CompareRaw, toVerdict, type Verdict, toSsErr, passBasis, roundMetrics, METRIC_F, ROUND0_F, type SsErr, metricZh, unitOfKey } from "./fieldmap";
// #62 调参页「自动迭代」（本地服务 #38：agent_tool iterate_start / iterate_cancel；事件 iterate.started / round / stopped）
// 纯状态机 + 文案；main.ts 只做 DOM 接线。预算一律以本地服务报的 limits 为准，没报前按板型兜底（实机 8 轮、仿真 20 轮、180 s）。
export type Limits = { time_s: number; rounds: number };
export const DEFAULT_LIMITS = (sim: boolean): Limits => ({ time_s: 180, rounds: sim ? 20 : 8 });
export type Gap = { value: number; limit: number; gap: number; unit: string };
export type Best = { iter: number; params: Record<string, number>; params_hash?: string; metrics?: Record<string, unknown>; pass?: unknown; gaps?: Record<string, Gap> };
export type Stopped = { reason: string; message_zh?: string; rounds?: number; best?: Best | null; next_zh?: string; best_card?: number | null; ss_err?: SsErr | null; pass_basis?: string; verdict?: Verdict; verdict_zh?: string; base?: Record<string, number> | null; compare?: CompareRaw | null };
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
export const runText = (iter: number, l: Limits, elapsedS: number) => `第 ${Math.min(Math.max(iter, 1), l.rounds)}/${l.rounds} 轮，预算还剩 ${Math.max(0, Math.ceil(l.time_s - elapsedS))} s`;
void mmss;
export const REASON_ZH: Record<string, string> = {
  autopilot: "自动调参结束", pass: "满足停止条件", budget_time: "时间预算用完", budget_rounds: "轮数用完", estop: "急停", stopped: "已手动停止",
  // r9p6 不可行情形：一律白话，结论只能是未达标 / 未判定
  saturation: "输出一直顶在限幅上（执行器饱和），再调增益也没用", saturated: "输出一直顶在限幅上（执行器饱和），再调增益也没用",
  delay: "系统延迟太大，按现在的采样周期调不稳", delay_too_large: "系统延迟太大，按现在的采样周期调不稳",
  unstable_zero: "对象有不稳定零点（非最小相位），单靠 PID 达不到指标", nonmin_phase: "对象有不稳定零点（非最小相位），单靠 PID 达不到指标",
  infeasible: "按现在的硬件和指标，这组目标达不到", no_signal: "反馈信号没变化，检查传感器或接线",
  invalid: "连续 3 轮无效", no_improve: "连续 3 轮没有改进", unstable: "出现发散", blocked: "各方向都被挡住", error: "出错",
};
const GAP_ZH: Record<string, string> = { overshoot: "超调", ss_err: "稳态误差", settle: "调节时间", rise: "上升时间" };
const n = (v: number) => v == null || !Number.isFinite(+v) ? "—" : String(+(+v).toPrecision(4));
export function gapLines(g: Record<string, Gap> | undefined, pass?: unknown, basis = ""): string[] {
  const ks = Object.keys(g ?? {});
  void basis;   // 结论只来自后端 verdict_zh，前端不再拼「达标」
  if (!ks.length) return pass ? [] : ["这一轮没有完整指标"];
  return ks.map(k => { const x = g![k], u = x.unit === "abs" ? "" : x.unit; return `${GAP_ZH[k] ?? k}：${n(x.value)}${u}，目标 ≤ ${n(x.limit)}${u}，差 ${n(x.gap)}${u}`; });
}
// 稳态误差 vs 题目误差带（卡 args.ss_err）：实测值 / 误差带+出处 / 是否在带内；单位对不上（inside=null）只提示先标定，不判过不过
export function bandLines(e: SsErr | null | undefined): string[] {
  if (!e) return [];
  const band = e.limit != null ? `题目误差带 ≤ ${n(e.limit)}${e.limitUnit ? " " + e.limitUnit : ""}` : "题目误差带未给";
  const verdict = e.inside === null ? "单位不一致，需先标定" : e.inside ? "在带内" : "超出误差带";
  const out = [`稳态误差 实测 ${n(e.measured)}${e.unit ? " " + e.unit : ""} / ${band} · ${verdict}`];
  if (e.source) out.push(`误差带来源：${e.source}`);
  if (e.note) out.push(e.note);
  return out;
}
// 第 0 轮 vs 最好一轮：[指标, 第0轮, 最好, 变化, 好/坏]；越小越好
export function compareRows(base: Record<string, number> | null | undefined, best: Record<string, unknown> | undefined): string[][] {
  if (!base || !best) return [];
  // r9p6：已知指标按固定顺序在前，其余（任意题目的自定义指标）跟在后面；单位按后缀推断，推不出就不写
  const known = METRIC_F.map(m => m[0]), keys = [...known, ...Object.keys(base).filter(k => !known.includes(k)).sort()];
  return keys.filter(k => typeof base[k] === "number" && Number.isFinite(base[k]) && typeof best[k] === "number" && Number.isFinite(best[k] as number)).map(k => {
    const zh = metricZh(k), u = unitOfKey(k), sp = (x: string) => u ? `${x} ${u}` : x;
    const a = Math.abs(base[k]), b = Math.abs(best[k] as number), d = b - a, pct = a ? Math.round(d / a * 100) : 0;
    return [zh, sp(n(a)), sp(n(b)), d === 0 ? "—" : `${d < 0 ? "↓" : "↑"} ${sp(n(Math.abs(d)))}${a ? `（${pct > 0 ? "+" : ""}${pct}%）` : ""}`, d < 0 ? "good" : d > 0 ? "bad" : ""];
  });
}
export function verdictLine(v: Verdict | undefined, e: SsErr | null, basis: string): { v: string; text: string } {
  const x: Verdict = !v || e?.inside === null ? { v: "unknown", zh: v?.v === "unknown" && v.zh ? v.zh : "未判定" } : v;
  return { v: x.v, text: `${x.zh}${basis && !x.zh.includes(basis) ? `（${basis}）` : ""}` };
}
// events.md compare：round0 / best 各是 [{key,value,unit}]，按 key 对齐
export function compareRaw(c: CompareRaw): string[][] {
  return c.round0.filter(a => c.best.some(x => x.key === a.key)).map(a => {
    const bb = c.best.find(x => x.key === a.key)!, x = Math.abs(a.value), y = Math.abs(bb.value), d = y - x, pct = x ? Math.round(d / x * 100) : 0, u = bb.unit || a.unit;
    return [METRIC_ZH[a.key] ?? a.key, `${n(x)} ${a.unit}`, `${n(y)} ${u}`, d === 0 ? "—" : `${d < 0 ? "↓" : "↑"} ${n(Math.abs(d))} ${u}${x ? `（${pct > 0 ? "+" : ""}${pct}%）` : ""}`, d < 0 ? "good" : d > 0 ? "bad" : ""];
  });
}
// #101 r9f：stopped 没带 best 时用台账里最好的有效一轮（同一份数据，卡片不和台账矛盾）
export function ledgerBest(r: Stopped, rs: readonly LedgerRound[] = LEDGER.all()): Best | null {
  if (r.best) return r.best;
  const lb = bestValid(rs); return lb ? { iter: lb.n, params: lb.params, metrics: lb.metrics } : null;
}
export function cardView(r: Stopped, rs: readonly LedgerRound[] = LEDGER.all()): { verdict: { v: string; text: string }; title: string; reason: string; params: [string, string][]; gaps: string[]; canWrite: boolean; next: string; compare: string[][] } {
  const b = ledgerBest(r, rs), basis = r.pass_basis ?? "", e = r.ss_err ?? null, zero = !!b && b.iter === 0;
  return {
    compare: r.compare && !r.compare.unchanged ? compareRaw(r.compare) : b && !zero ? compareRows(r.base, b.metrics) : [],
    title: !b ? "没有可用的一轮" : r.compare?.unchanged || zero ? (r.compare?.note && (!/达标/.test(r.compare.note) || verdictLine(r.verdict, e, "").v === "pass") ? r.compare.note : "初值已是最好一组，未改参") : `最好一组参数（第 ${b.iter} 轮）`,
    reason: `停止原因：${REASON_ZH[r.reason] ?? (r.reason ? `其他（${r.reason}）` : "未上报")}${r.message_zh ? `（${verdictLine(r.verdict, e, "").v === "pass" ? r.message_zh : r.message_zh.replace(/达标/g, "满足迭代条件")}）` : ""}`,
    params: b ? Object.entries(b.params).map(([k, v]) => [k, n(v)]) : [],
    gaps: b ? [...bandLines(e), ...gapLines(b.gaps, e?.inside === null || b.pass)] : [],
    verdict: verdictLine(r.verdict, e, basis),
    canWrite: !!b && !zero && Object.keys(b.params ?? {}).length > 0,
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
    if ((RESULT_CLEAR_EV as readonly string[]).includes(m?.type)) { this.reset(); LEDGER.reset(); return true; }
    if (m?.type === "iterate.round") { const lr = fromRoundEvent(m); if (lr) LEDGER.push(lr); }
    if (m?.type === "iterate.started") { const l = m.limits?.rounds ? { time_s: m.limits.time_s, rounds: m.limits.rounds } : this.s.limits; this.base = null; this.s = { phase: "running", limits: l, t0: now, iter: 0 }; return true; }
    if (m?.type === "iterate.round" && +m.iter === 0) this.base = roundMetrics(m);
    if (m?.type === "iterate.round") { if (this.s.phase !== "running") this.s = { phase: "running", limits: this.s.limits, t0: now, iter: 0 }; (this.s as any).iter = Math.max((this.s as any).iter, +m.iter || 0); return true; }
    if (m?.type === "iterate.stopped") { const id = this.s.phase === "done" ? this.s.result.best_card : undefined; const x = this.extra; this.s = { phase: "done", limits: this.s.limits, result: { ...m, base: roundMetrics(m[ROUND0_F.obj]) ?? this.base, best_card: m.best_card ?? id ?? null, ss_err: toSsErr(m) ?? x.ss_err ?? null, pass_basis: passBasis(m) || x.pass_basis || "", verdict: m.verdict ? toVerdict(m) : x.verdict, compare: toCompare(m) ?? x.compare ?? null } }; return true; }
    if (m?.type === "agent_action" && m.tool === APPLY_TOOL) { this.cardId = m.id; this.extra = { ss_err: toSsErr(m), pass_basis: passBasis(m), verdict: m.args?.verdict || m.preview?.verdict || m.verdict ? toVerdict(m) : undefined, compare: toCompare(m) }; this.cache?.set(JSON.stringify({ id: m.id, ...this.extra }));
      // 走的是 tune 自动调参（tune_round，无 iterate.stopped）时，卡本身就是结果：用卡参数合成结果，调参页照样出这一张
      if (this.s.phase !== "done") { const a = m.args ?? {}; this.s = { phase: "done", limits: this.s.limits, result: { reason: "autopilot", best: { iter: +a.iter || 0, params: a.params ?? {}, params_hash: a.params_hash }, best_card: m.id, ss_err: this.extra.ss_err, pass_basis: this.extra.pass_basis, verdict: this.extra.verdict, compare: this.extra.compare } }; return true; }
      if (this.s.phase === "done") { const r = this.s.result; r.best_card = m.id; r.ss_err = this.extra.ss_err; r.pass_basis = r.pass_basis || this.extra.pass_basis; r.verdict = this.extra.verdict ?? r.verdict; r.compare = this.extra.compare ?? r.compare; } return true; }
    return false;
  }
  cardId: number | null = null;
  base: Record<string, number> | null = null;
  extra: { ss_err: SsErr | null; pass_basis: string; verdict?: Verdict; compare?: CompareRaw | null } = { ss_err: null, pass_basis: "" };
  // 刷新后补回卡字段：优先 iterate_status 里的结果（后端按工程+板子存），否则用本地缓存的上一张卡（同 id）
  cache?: { get(): string | null; set(v: string): void };
  restored(res: any): { ss_err: SsErr | null; pass_basis: string; verdict?: Verdict; compare?: CompareRaw | null } {
    const card = res?.card ?? res?.param_card ?? res;
    let c: any = null; try { c = JSON.parse(this.cache?.get() ?? "null"); } catch { c = null; }
    const same = c && (res?.best_card == null || c.id === res.best_card);
    const hasV = card?.args?.verdict ?? card?.preview?.verdict ?? card?.verdict ?? res?.verdict;
    return {
      ss_err: toSsErr(card) ?? toSsErr(res) ?? (same ? c.ss_err : null),
      pass_basis: passBasis(card) || passBasis(res) || (same ? c.pass_basis || "" : ""),
      compare: toCompare(card) ?? toCompare(res) ?? (same ? c.compare : null),
      verdict: hasV ? toVerdict(card?.args?.verdict || card?.preview?.verdict || card?.verdict ? card : res) : same ? c.verdict : undefined,
    };
  }
  // 重连 / 刷新：iterate_status {running, result}
  onStatus(r0: any, now: number, dismissed?: number | null) {
    const r = r0 && !r0.result && r0.last?.result ? { ...r0, result: r0.last.result } : r0;   // events.md：内存没有时回落到按项目+板卡落盘的 last
    if (!r?.running && r?.result && r.result.best_card != null && r.result.best_card === dismissed) return;   // 已采用 / 已收起的结果不再出卡
    if (r?.running) { if (this.s.phase !== "running") this.s = { phase: "running", limits: this.s.limits, t0: now, iter: 0 }; }
    else if (r?.result && this.s.phase !== "done" && r.result.type !== "tune.stopped") this.s = { phase: "done", limits: this.s.limits, result: { ...r.result, best_card: r.result.best_card ?? null, ...this.restored(r.result) } };
    else if (r?.result?.type === "tune.stopped" && this.s.phase !== "done") this.s = { phase: "done", limits: this.s.limits, result: { reason: "autopilot", ...r.result, ...this.restored(r.result) } };
  }
  applyId(): number | null { return this.s.phase === "done" ? (this.s.result.best_card ?? this.cardId) : null; }
  // #101 结果是否属于当前板：结果带板卡字段且对不上 → 不恢复；不带 → 重连后一律不恢复（宁缺勿错）
  static sameBoard(res: any, port: string | null | undefined): boolean { const p = pickStr(res, RESULT_PORT_F); return !!p && !!port && p === port; }
  reset() { this.cache?.set("null"); this.cardId = null; this.extra = { ss_err: null, pass_basis: "" }; this.s = { phase: "idle", limits: this.s.limits }; }
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
// r9p4 结果卡：标题 = 结论（verdict_zh，不带依据）；一行对比 超调 / 调节时间 / 稳态误差（初值 → 最好）；
// 参数一行横排；判定依据 / 单位不一致 / 停止原因收进「详情」；唯一主按钮「采用这组参数」
export const CARD_KEYS = /超调|调节|稳态/;
export function resultCardHtml(r: Stopped, esc: (s: string) => string, o: { canApply: boolean; applyReady: boolean }): string {
  const v = cardView(r), head = verdictLine(r.verdict, r.ss_err ?? null, "").text.replace(/（.*$/, "");
  const key = v.compare.filter(x => CARD_KEYS.test(x[0])), cells = key.length ? key : v.compare.slice(0, 4);   // r9p6 别的题没有超调/调节/稳态时，照样列出它自己的指标
  const cmp = cells.length
    ? `<div class="rc-cmp">${cells.map(x => `<div class="rc-m"><span class="rc-k">${esc(x[0])}</span><span class="rc-v num">${esc(x[1])} → <b>${esc(x[2])}</b></span><span class="rc-d num ${x[4] ?? ""}">${esc(x[3])}</span></div>`).join("")}</div>`
    : `<p class="rc-cur num">${esc(currentMetrics(r))}</p><p class="rc-same">${esc(v.title)}</p>`;
  const ps = `<div class="rc-ps">${v.params.map(([k, x]) => `<span class="mono"><i>${esc(k)}</i> ${esc(x)}</span>`).join("")}</div>`;
  const det = `<details class="rc-det"><summary>详情</summary>${[v.verdict.text, ...v.gaps, v.reason, v.next].filter(Boolean).map(t => `<p>${esc(t)}</p>`).join("")}</details>`;
  const btn = o.canApply && v.canWrite ? `<wa-button variant="brand" size="small" id="it-write"${o.applyReady ? "" : ' disabled title="等本地服务出确认卡…"'}>采用这组参数</wa-button>` : "";
  // r9p6 没达标 / 未判定：原因直接写在标题下（白话），不藏进详情，也绝不显示成达标样式
  const why = v.verdict.v !== "pass" ? `<p class="rc-why">${esc(v.reason.replace(/^停止原因：/, "原因："))}</p>` : "";
  return `<wa-card class="itc rc"><h4 class="it-verdict ${v.verdict.v}" id="it-verdict">${esc(head)}${coarseTagHtml(r)}</h4>${why}${cmp}${ps}${det}<span class="it-act">${btn}<wa-button appearance="plain" size="small" id="it-x">收起</wa-button></span></wa-card>`;
}

// r9p5 未改参 / 没有对比数据时也要有指标行：只列当前值，缺的写「—」，不画箭头
const CUR_KEYS: [string, string[], (v: number, u: string) => string][] = [
  ["超调", ["overshoot_pct", "overshoot"], (v, u) => `${n(Math.abs(v))}${u || "%"}`],
  ["调节", ["settling_s", "settle_s", "settle_ms", "settling"], (v, u) => u === "ms" || (!u && v > 50) ? `${n(v / 1000)} s` : `${n(v)} ${u || "s"}`],
  ["稳态误差", ["ss_err", "ss_err_pct", "sse_pct", "sse"], (v, u) => `${n(Math.abs(v))}${u ? (u === "%" ? "%" : " " + u) : ""}`],
];
export function currentMetrics(r: Stopped): string {
  const pools: { key: string; value: number; unit: string }[][] = [];
  const c: any = r.compare; if (c?.best?.length) pools.push(c.best); if (c?.round0?.length) pools.push(c.round0);
  const obj = (o: any, unitOf: (k: string) => string) => o ? Object.entries(o).filter(([, v]) => typeof v === "number").map(([key, value]) => ({ key, value: value as number, unit: unitOf(key) })) : [];
  const uf = unitOfKey;
  pools.push(obj(r.best?.metrics, uf), obj(r.base, uf));
  const e: any = r.ss_err; if (e && typeof e.measured === "number") pools.push([{ key: "ss_err", value: e.measured, unit: e.unit ?? "" }]);
  return CUR_KEYS.map(([zh, keys, f]) => {
    for (const pl of pools) { const m = pl.find(x => keys.includes(x.key) && Number.isFinite(x.value)); if (m) return `${zh} ${f(m.value, m.unit)}`; }
    return `${zh} —`;
  }).join(" · ");
}
