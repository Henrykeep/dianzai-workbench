// #111 r9f：待确认的提交卡刷新后不丢——sessionStorage 兜底，按 request_id 去重；后端重推 / 出结果时对账
import { COMMIT_F, COMMIT_STORE_KEY } from "./fieldmap";
type St = Pick<Storage, "getItem" | "setItem">;
const idOf = (m: any) => (m?.[COMMIT_F.id] != null ? String(m[COMMIT_F.id]) : "");
export function loadPending(st: St | null): any[] {
  try { const a = JSON.parse(st?.getItem(COMMIT_STORE_KEY) || "[]"); return Array.isArray(a) ? a.filter(x => idOf(x)) : []; } catch { return []; }
}
function save(st: St | null, a: any[]) { try { st?.setItem(COMMIT_STORE_KEY, JSON.stringify(a)); } catch { /* 存不下就算了 */ } }
export function keepPending(st: St | null, m: any) { const id = idOf(m); if (!id) return; save(st, [...loadPending(st).filter(x => idOf(x) !== id), m]); }
export function dropPending(st: St | null, id: string) { save(st, loadPending(st).filter(x => idOf(x) !== id)); }
