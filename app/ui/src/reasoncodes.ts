// #139 停止原因中文：握手 data_tables.reason_codes 优先，界面打包的 docs/dev/reason_codes.json 其次，再是前端兜底表
import { DataTable, validReasons, type ReasonMap } from "./datatables";
export type ReasonCode = { zh: string; kind?: string };
export const UNKNOWN_REASON_ZH = "未知原因";
export const REASONS_T = new DataTable<ReasonMap>("reason_codes", "原因表", validReasons, {}, true);
declare const __DZ_REASON_SHA__: string | null;
try {
  const g: Record<string, any> = typeof (import.meta as any).glob === "function" ? import.meta.glob("../../../docs/dev/reason_codes.json", { eager: true, import: "default" }) : {};
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
