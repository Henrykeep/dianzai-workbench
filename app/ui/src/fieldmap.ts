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
export const passBasis = (src: any): string => str(src?.[PASS_BASIS_F] ?? src?.args?.[PASS_BASIS_F] ?? src?.preview?.[PASS_BASIS_F]);
