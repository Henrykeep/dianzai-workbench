// 本地服务事件字段名 → 界面内部形状的唯一映射点（见 docs/dev/events.md）。字段改名只改这里的常量，
// 界面其余代码只用 toRetry / toSsErr / passBasis 的返回值。
export const RETRY_F = { type: "llm_retry", attempt: "attempt", total: "max", wait: "wait_s", fix: "fix_action", msg: "message_zh", localFix: "switch_local_model" } as const;
// “采用最好参数”卡 args.ss_err / preview.ss_err：{measured, unit, band:{limit, unit, item, source}, inside, note_zh}
export const SSERR_F = { obj: "ss_err", measured: "measured", unit: "unit", band: "band", limit: "limit", bUnit: "unit", item: "item", source: "source", inside: "inside", note: "note_zh" } as const;
// 达标口径（可选，后端尚未推）：卡 args/preview 或 iterate.stopped 上的 pass_basis
export const PASS_BASIS_F = "pass_basis";
export type Retry = { attempt: number; total: number; wait?: number; fix?: string; msg?: string };
export type SsErr = { measured: number; unit: string; limit?: number; limitUnit: string; item: string; source: string; inside: boolean | null; note: string };
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const str = (v: unknown) => (typeof v === "string" ? v : "");
export const isRetry = (m: any) => m?.type === RETRY_F.type;
export function toRetry(m: any): Retry {
  return { attempt: num(m?.[RETRY_F.attempt]) ?? 1, total: num(m?.[RETRY_F.total]) ?? 1, wait: num(m?.[RETRY_F.wait]), fix: m?.[RETRY_F.fix] || undefined, msg: str(m?.[RETRY_F.msg]) || undefined };
}
// 从卡（agent_action）或已存的结果里取 ss_err；没有或缺实测值 → null
export function toSsErr(src: any): SsErr | null {
  const o = src?.args?.[SSERR_F.obj] ?? src?.preview?.[SSERR_F.obj] ?? src?.[SSERR_F.obj];
  const v = num(o?.[SSERR_F.measured]); if (v == null) return null;
  const b = o[SSERR_F.band] ?? {};
  const ins = o[SSERR_F.inside];
  return { measured: v, unit: str(o[SSERR_F.unit]), limit: num(b[SSERR_F.limit]), limitUnit: str(b[SSERR_F.bUnit]), item: str(b[SSERR_F.item]), source: str(b[SSERR_F.source]), inside: typeof ins === "boolean" ? ins : null, note: str(o[SSERR_F.note]) };
}
export const passBasis = (src: any): string => str(src?.[PASS_BASIS_F] ?? src?.args?.[PASS_BASIS_F] ?? src?.preview?.[PASS_BASIS_F] ?? src?.args?.ss_err?.[PASS_BASIS_F] ?? src?.preview?.ss_err?.[PASS_BASIS_F] ?? src?.ss_err?.[PASS_BASIS_F] ?? src?.card?.args?.[PASS_BASIS_F]);
// 第 0 轮（初值）指标：后端补字段前从 iterate.round(iter=0) 取；字段名定稿后改这里
export const ROUND0_F = { obj: "round0", metrics: "metrics" } as const;
export const METRIC_F: [key: string, zh: string, unit: string][] = [["ss_err_pct", "稳态误差", "%"], ["overshoot_pct", "超调", "%"], ["settle_ms", "调节时间", "ms"], ["rise_ms", "上升时间", "ms"]];
export const roundMetrics = (m: any): Record<string, number> | null => { const o = m?.[ROUND0_F.metrics] ?? m; return o && METRIC_F.some(([k]) => typeof o[k] === "number") ? o : null; };
// 右栏 Agent 状态：status.agent.state ∈ ready | unconfigured | busy（fix_action configure_model）；后端没给时退回 agent_config.configured
export const AGENT_F = { obj: "agent", state: "state", fix: "fix_action", cfgFix: "configure_model" } as const;
export type AgentState = "ready" | "unconfigured" | "busy";
export function agentState(status: any): AgentState | null { const v = status?.[AGENT_F.obj]?.[AGENT_F.state]; return v === "ready" || v === "unconfigured" || v === "busy" ? v : null; }
// 建议卡来源：rule / rules / 规则 → 规则引擎；llm / model / agent → 模型
export const SOURCE_F = "source";
export function sourceLabel(m: any): string {
  const s = String(m?.[SOURCE_F] ?? m?.preview?.[SOURCE_F] ?? m?.args?.[SOURCE_F] ?? "").toLowerCase();
  const zh = str(m?.source_zh ?? m?.preview?.source_zh ?? m?.args?.source_zh);
  if (s === "rule_engine") return zh && zh !== "规则引擎" ? `来自规则引擎 · ${zh}` : "来自规则引擎";
  if (s === "llm") return "来自模型";
  return /rule|规则/.test(s) ? "来自规则引擎" : /llm|model|agent|模型/.test(s) ? "来自模型" : "";
}
// 卡结论（后端定稿前可选）：verdict ∈ pass|fail|unknown + verdict_zh。结论只显示 verdict_zh；缺 verdict → 中性「未判定」，绝不当作达标
export const VERDICT_F = { v: "verdict", zh: "verdict_zh" } as const;
export type Verdict = { v: "pass" | "fail" | "unknown"; zh: string };
export function toVerdict(src: any): Verdict {
  const pick = (k: string) => src?.args?.[k] ?? src?.preview?.[k] ?? src?.[k];
  const v = pick(VERDICT_F.v), zh = str(pick(VERDICT_F.zh));
  if (v === "pass" || v === "fail" || v === "unknown") return { v, zh: zh || (v === "unknown" ? "未判定" : "") || "未判定" };
  return { v: "unknown", zh: "未判定" };
}
// 换示例：op project_switch_example {example}；回 project_forked {example, project, path, message_zh}
export const SWITCH_EX_OP = "project_switch_example";
export const FORKED_F = { type: "project_forked", example: "example", project: "project", msg: "message_zh", alts: "examples" } as const;
// 卡 args.compare / preview.compare（events.md）：{round0:{iter, metrics:[{key,value,unit}]}, best:{…}, unchanged, note_zh}；iterate.stopped 顶层也带 round0
export const COMPARE_F = { obj: "compare", r0: "round0", best: "best", metrics: "metrics", unchanged: "unchanged", note: "note_zh" } as const;
export type MetricV = { key: string; value: number; unit: string };
export type CompareRaw = { round0: MetricV[]; best: MetricV[]; unchanged: boolean; note: string };
export const METRIC_ZH: Record<string, string> = { ss_err_pct: "稳态误差", ss_err: "稳态误差", sse_pct: "稳态误差", settling_s: "调节时间", settle_s: "调节时间", rise_s: "上升时间", sse: "稳态误差", overshoot_pct: "超调", overshoot: "超调", settle_ms: "调节时间", settling: "调节时间", iae: "误差积分 IAE", rise_ms: "上升时间" };
const mlist = (o: any): MetricV[] => (Array.isArray(o?.[COMPARE_F.metrics]) ? o[COMPARE_F.metrics] : []).filter((x: any) => typeof x?.value === "number").map((x: any) => ({ key: str(x.key), value: x.value, unit: str(x.unit) }));
export function toCompare(src: any): CompareRaw | null {
  const c = src?.args?.[COMPARE_F.obj] ?? src?.preview?.[COMPARE_F.obj] ?? src?.[COMPARE_F.obj] ?? (src?.[COMPARE_F.r0] ? { round0: src[COMPARE_F.r0], best: src.best } : null);
  if (!c) return null;
  const r0 = mlist(c[COMPARE_F.r0]), b = mlist(c[COMPARE_F.best]);
  if (!r0.length && !b.length && !c[COMPARE_F.unchanged]) return null;
  return { round0: r0, best: b, unchanged: c[COMPARE_F.unchanged] === true, note: str(c[COMPARE_F.note]) };
}
