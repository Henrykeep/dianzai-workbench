// #101 r9f：结果卡和台账同一份数据。台账每记一轮（阶跃实验 / iterate.round）都进这里；
// 结果卡没拿到 stopped.best 时取这里「最好的有效一轮」，不会出现台账有有效轮、卡片却说“没有可用的一轮”。
import { LEDGER_ROUND_F as F } from "./fieldmap";
export type LedgerRound = { n: number; params: Record<string, number>; metrics: Record<string, number>; valid: boolean };
const rounds: LedgerRound[] = [];
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export const LEDGER = {
  push(r: LedgerRound) { const i = rounds.findIndex(x => x.n === r.n && JSON.stringify(x.params) === JSON.stringify(r.params)); if (i >= 0) rounds[i] = r; else rounds.push(r); },
  reset() { rounds.length = 0; },
  all(): readonly LedgerRound[] { return rounds; },
};
export function fromRoundEvent(m: any): LedgerRound | null {
  if (!m || !fin(+m[F.iter])) return null;
  const metrics: Record<string, number> = {};
  for (const k of [F.overshoot, F.settle]) if (fin(m[k])) metrics[k] = m[k];
  const p = m[F.params] && typeof m[F.params] === "object" ? m[F.params] : {};
  return { n: +m[F.iter], params: p, metrics, valid: m[F.valid] !== false && Object.keys(metrics).length > 0 };
}
// 最好的有效一轮：有效 + 有指标；按 |超调| 小、再按调节时间短
export function bestValid(rs: readonly LedgerRound[]): LedgerRound | null {
  const v = rs.filter(r => r.valid && fin(r.metrics[F.overshoot]));
  if (!v.length) return null;
  const s = (r: LedgerRound) => [Math.abs(r.metrics[F.overshoot]), fin(r.metrics[F.settle]) ? r.metrics[F.settle] : Infinity];
  return v.reduce((a, b) => { const [x1, y1] = s(a), [x2, y2] = s(b); return x2 < x1 || (x2 === x1 && y2 < y1) ? b : a; });
}
