// #139 停止原因中文：握手 data_tables.reason_codes 优先，界面打包的 docs/dev/reason_codes.json 其次，再是前端兜底表
import { DataTable, validReasons, type ReasonMap } from "./datatables";
export type ReasonCode = { zh: string; kind?: string };
export const UNKNOWN_REASON_ZH = "未知原因";
export const REASONS_T = new DataTable<ReasonMap>("reason_codes", "原因表", validReasons, {}, true);
declare const __DZ_REASON_JSON__: unknown;
declare const __DZ_REASON_SHA__: string | null;
try {
  const g: Record<string, any> = typeof (import.meta as any).glob === "function" ? import.meta.glob("../../../docs/dev/reason_codes.json", { eager: true, import: "default" }) : {};
  if (!Object.keys(g).length && typeof __DZ_REASON_JSON__ !== "undefined") g.inj = __DZ_REASON_JSON__;
  REASONS_T.setBundled(Object.values(g)[0] ?? null, typeof __DZ_REASON_SHA__ === "string" ? __DZ_REASON_SHA__ : null);
} catch { /* 兜底表 */ }
const DEV = (() => { try { return !!(import.meta as any).env?.DEV; } catch { return false; } })();
export const setReasonCodes = (o: unknown, sha: string | null = null) => REASONS_T.setBundled(o, sha);
export const reasonCodes = () => REASONS_T.value();
export const reasonCodesNotice = (dev = DEV) => REASONS_T.notice(dev);
export function reasonZh(code: string | undefined | null, fallback: Record<string, string>): string {
  if (!code) return "未上报";
  return REASONS_T.value()[code]?.zh ?? fallback[code] ?? UNKNOWN_REASON_ZH;
}
export const reasonKind = (code: string | undefined | null): string => (code && (REASONS_T.value()[code]?.kind as string)) || "";

// r10w 通用渲染：可能原因（事件给的优先，没有就用原因表的）+ 停输出标志（事件或原因表）
import { STOP_CAUSE_F as SC } from "./fieldmap";
export function stopCauses(r: any): { causes: string[]; stopped: boolean } {
  const e = r?.reason ? REASONS_T.value()[r.reason] : undefined;
  const one = (c: any): string => typeof c === "string" ? (REASONS_T.value()[c]?.zh ?? c) : c && typeof c === "object" ? String(c[SC.zh] ?? c[SC.msgZh] ?? (c[SC.code] ? REASONS_T.value()[c[SC.code]]?.zh ?? "" : "")) : "";
  const ev = Array.isArray(r?.[SC.causes]) ? r[SC.causes].map(one).filter(Boolean) : [];
  return { causes: ev.length ? ev : e?.causes ?? [], stopped: SC.stopFlags.some(k => r?.[k] === true) || e?.stop === true };
}
