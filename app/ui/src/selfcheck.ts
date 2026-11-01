// 「运行自检」：本地服务连着 → op selfcheck_data；连不上 → Tauri 跑安装目录里固定的自检脚本（同样输出 {ok, items}）；都不行 → 按平台给菜单入口提示
// 面向用户的文字里不出现命令行和文件名
import { SELFCHECK_F, SELFCHECK_FIX_ZH, SELFCHECK_FILE_ZH, SELFCHECK_ST_ZH, SELFCHECK_UNCHECKED, SELFCHECK_EXIT, readableZh } from "./fieldmap";
export type SelfItem = { file: string; status: string; message_zh: string; fix_action: string };
export type SelfResult = { src: "service" | "local" | "none"; ok: boolean | null; items: SelfItem[]; error?: string; exit?: number | null };
const esc = (s: string) => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" } as any)[c]);
export function parseSelf(r: any): { ok: boolean | null; items: SelfItem[]; exit?: number | null } | null {
  const o = typeof r === "string" ? (() => { try { return JSON.parse(r); } catch { return null; } })() : r;
  if (o && typeof o === "object" && SELFCHECK_F.report in o) { const p = parseSelf(o[SELFCHECK_F.report]); return p && { ...p, exit: typeof o[SELFCHECK_F.exit] === "number" ? o[SELFCHECK_F.exit] : null }; }   // Tauri 包装 {exit_code, report}
  if (!o || typeof o !== "object" || !Array.isArray(o[SELFCHECK_F.items])) return null;
  const s = (v: unknown) => typeof v === "string" ? v : "";
  return { ok: typeof o[SELFCHECK_F.ok] === "boolean" ? o[SELFCHECK_F.ok] : null, items: o[SELFCHECK_F.items].map((x: any) => ({ file: s(x?.[SELFCHECK_F.file]), status: s(x?.[SELFCHECK_F.status]), message_zh: s(x?.[SELFCHECK_F.msg]), fix_action: s(x?.[SELFCHECK_F.fix]) })) };
}
// 文件名 → 中文名（不显示文件名）
export const fileZh = (f: string) => { const b = f.split(/[\\/]/).pop() ?? ""; return SELFCHECK_FILE_ZH[b] ?? "数据文件"; };
export const lastResortZh = (ua = typeof navigator !== "undefined" ? navigator.userAgent : "") =>
  /Windows/i.test(ua) ? "请运行开始菜单里的『芯台 自检』" : "请运行应用菜单里的『芯台 自检』，或按使用说明里的「自检」一节操作";
export async function runSelfcheck(o: { connected: boolean; call: (op: string) => Promise<any>; invoke?: ((cmd: string) => Promise<any>) | null }): Promise<SelfResult> {
  let svcErr = "";
  if (o.connected) {   // connected = 本地服务（WebSocket）连着；不要求板子在线，selfcheck_data 只查数据文件
    try { const p = parseSelf(await o.call(SELFCHECK_F.op)); if (p) return { src: "service", ...p }; svcErr = "本地服务的自检回复看不懂"; }
    catch (e: any) { svcErr = (typeof e?.message_zh === "string" && e.message_zh) || "本地服务不支持自检（可能是旧版本或模拟器）"; }
  }
  if (o.invoke) {
    try { const p = parseSelf(await o.invoke(SELFCHECK_F.tauriCmd)); if (p) return { src: "local", ...p, error: svcErr || undefined }; } catch { /* 跑不起来 → 菜单提示 */ }
  }
  return { src: "none", ok: null, items: [], error: [svcErr, lastResortZh()].filter(Boolean).join("。") };
}
// 汇总：未检查单独计数，有未检查就绝不说「全部正常」
export const isUnchecked = (st: string) => SELFCHECK_UNCHECKED.includes(st);
export function selfSummary(r: SelfResult): { ok: number; bad: number; unchecked: number; text: string; tone: "ok" | "warn" | "bad" } {
  const unchecked = r.items.filter(x => isUnchecked(x.status)).length, ok = r.items.filter(x => x.status === "ok").length, bad = r.items.length - ok - unchecked;
  const parts = [`${ok} 项正常`, bad ? `${bad} 项有问题` : "", unchecked ? `${unchecked} 项未检查` : ""].filter(Boolean).join("，");
  if (!r.items.length && r.exit !== SELFCHECK_EXIT.incomplete) return { ok, bad, unchecked, text: "", tone: "warn" };
  if (bad || r.exit === SELFCHECK_EXIT.fail || (r.ok === false && !unchecked && r.exit !== SELFCHECK_EXIT.incomplete)) return { ok, bad, unchecked, text: parts, tone: "bad" };
  if (unchecked || r.exit === SELFCHECK_EXIT.incomplete) return { ok, bad, unchecked, text: `自检未完成：${unchecked} 项未检查`, tone: "warn" };
  return { ok, bad, unchecked, text: "全部正常", tone: "ok" };
}
export function selfcheckHtml(r: SelfResult | null): string {
  if (!r) return `<p class="hint">正在自检…</p>`;
  const rows = r.items.map(x => `<tr class="sc-${isUnchecked(x.status) ? "unchecked" : esc(x.status)}"><td>${esc(fileZh(x.file))}</td><td>${esc(SELFCHECK_ST_ZH[x.status] ?? "未知")}</td><td>${esc(readableZh(x.message_zh || "—"))}</td><td>${x.fix_action && SELFCHECK_FIX_ZH[x.fix_action] ? `<button class="btn sm" data-sc-fix="${esc(x.fix_action)}">${esc(SELFCHECK_FIX_ZH[x.fix_action][0])}</button>` : ""}</td></tr>`).join("");
  const head = r.src === "service" ? "本地服务自检" : r.src === "local" ? "本机自检（本地服务未连接）" : "没能运行自检";
  return `<div class="card sc-card" id="sc-card"><b>${head}</b>${(() => { const m = selfSummary(r); return m.text ? `<p class="sc-sum sc-sum-${m.tone}">${esc(m.text)}</p>` : ""; })()}${r.error ? `<p class="warn-t">${esc(readableZh(r.error))}</p>` : ""}` +
    (rows ? `<table class="sc-t"><thead><tr><th>项目</th><th>状态</th><th>说明</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : "") +
    `<p class="sc-guide" id="sc-guide" hidden></p><button class="btn sm" id="sc-x">关闭</button></div>`;
}
export const fixGuideZh = (a: string) => SELFCHECK_FIX_ZH[a]?.[1] ?? "";
export const SELFCHECK_BTN_HTML = `<button class="btn sm" data-selfcheck>运行自检</button>`;
