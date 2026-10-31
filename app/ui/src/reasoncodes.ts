// #139 停止原因中文的唯一来源：后端 docs/dev/reason_codes.json {code: {zh, kind}}（随 #123 发布）；没有这个文件就用前端兜底表
export type ReasonCode = { zh: string; kind?: string };
export const UNKNOWN_REASON_ZH = "未知原因";
import { dataNoticeZh } from "./fieldmap";
let CODES: Record<string, ReasonCode> = {};
let ST: "ok" | "missing" | "bad" = "missing";
export const reasonCodesStatus = () => ST;
export const reasonCodesNotice = () => dataNoticeZh("原因表", ST);
export function setReasonCodes(o: unknown) {
  CODES = {};
  if (o == null) { ST = "missing"; return; }
  ST = "bad";
  if (typeof o !== "object" || Array.isArray(o)) return;
  const es = Object.entries(o as any);
  if (!es.length || !es.every(([, v]) => v && typeof (v as any).zh === "string" && (v as any).zh)) return;   // 有一条不合格就整表不用，免得半套中文
  for (const [k, v] of es) CODES[k] = { zh: (v as any).zh, kind: (v as any).kind };
  ST = "ok";
}
export const reasonCodes = () => CODES;
// 构建时由 Vite 打包（文件不存在就是空对象）；tsx 测试里没有 import.meta.glob，由测试自己 setReasonCodes
try {
  const g: Record<string, any> = typeof (import.meta as any).glob === "function" ? import.meta.glob("../../../docs/dev/reason_codes.json", { eager: true, import: "default" }) : {};
  setReasonCodes(Object.values(g)[0] ?? null);
} catch { /* 兜底表 */ }
export function reasonZh(code: string | undefined | null, fallback: Record<string, string>): string {
  if (!code) return "未上报";
  return CODES[code]?.zh ?? fallback[code] ?? UNKNOWN_REASON_ZH;
}
