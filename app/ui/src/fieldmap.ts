// 本地服务事件字段名 → 界面内部形状的唯一映射点。llm_retry 与参数卡误差带的字段名尚未定稿：
// 等后端 events.md 定名后只改这里的常量，界面其余代码只用 toRetry / toBand 的返回值。
export const RETRY_F = { type: "llm_retry", attempt: "attempt", total: "total", wait: "wait_s", fix: "fix_action" } as const;
export const BAND_F = {
  obj: "ss_band", value: "value", band: "band", inBand: "in_band", unit: "unit", source: "source",   // best.ss_band{…}（拟定）
  m: "metrics", mErr: "ss_err_pct", mBand: "band", mMode: "metric_mode", pass: "pass", passKey: "ss_err",   // 退回 best.metrics（现有）
  mSource: "板上阶跃 step_result",
} as const;
export type Retry = { attempt: number; total: number; wait?: number; fix?: string };
export type Band = { value: number; band: number; in_band: boolean; unit: string; source: string };
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
export const isRetry = (m: any) => m?.type === RETRY_F.type;
export function toRetry(m: any): Retry {
  return { attempt: num(m?.[RETRY_F.attempt]) ?? 1, total: num(m?.[RETRY_F.total]) ?? 1, wait: num(m?.[RETRY_F.wait]), fix: m?.[RETRY_F.fix] || undefined };
}
export function toBand(best: any): Band | null {
  const o = best?.[BAND_F.obj];
  if (o && num(o[BAND_F.band]) != null && num(o[BAND_F.value]) != null)
    return { value: o[BAND_F.value], band: o[BAND_F.band], in_band: o[BAND_F.inBand] === true, unit: o[BAND_F.unit] ?? "", source: o[BAND_F.source] ?? "" };
  const m = best?.[BAND_F.m], v = num(m?.[BAND_F.mErr]), b = num(m?.[BAND_F.mBand]);
  if (v == null || b == null) return null;
  const p = best?.[BAND_F.pass]?.[BAND_F.passKey];
  return { value: v, band: b, in_band: typeof p === "boolean" ? p : Math.abs(v) <= b, unit: m[BAND_F.mMode] === "abs" ? "" : "%", source: BAND_F.mSource };
}
