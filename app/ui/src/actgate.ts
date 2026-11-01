// r10x 执行器闸门：正在恢复连接（resuming）/ 板子身份未定（pending）/ 急停中暂不识别（estop_latched_ident_deferred）
// 任一成立 → 禁用所有驱动执行器的控件；横幅文案按 reason_codes + message_zh 通用渲染，前端不拼
import { GATE_F as G, BOARD_PENDING_ZH, RESUME_TO_F, isResumeTimeout } from "./fieldmap";
import { REASONS_T } from "./reasoncodes";
export type Gate = { code: string; text: string; reconnect?: boolean };
const s = (v: unknown) => typeof v === "string" && v ? v : null;
// 原因码 → 中文：事件 message_zh 优先，其次原因表 zh，再兜底
export function reasonText(code: string, x?: any, fb = ""): string {
  return s(x?.message_zh) ?? s(x?.data?.message_zh) ?? s(REASONS_T.value()[code]?.zh) ?? (fb || code);
}
// error 回包 / 阻塞项 / 事件里拿原因码
export const codeOf = (x: any): string | null => !x || typeof x !== "object" ? null : s(x.reason) ?? s(x.code) ?? s(x.blocker_code) ?? s(x.data?.reason) ?? null;
export const isGateCode = (c: string | null) => c === G.resuming || c === G.deferred;
export const deferredOf = (x: any): Gate | null => codeOf(x) === G.deferred ? { code: G.deferred, text: reasonText(G.deferred, x, G.deferredZh) } : null;
export const fromBlockersGate = (bs: any[] | null | undefined) => { for (const b of bs ?? []) { const g = deferredOf(b); if (g) return g; } return null; };
// 优先级：恢复连接 > 急停中暂不识别 > 身份未定
export function actGateOf(o: { link?: any; pending?: boolean; deferred?: Gate | null }): Gate | null {
  if (isResumeTimeout(o.link)) { const c = s(o.link.reason) ?? RESUME_TO_F.codes[0]; return { code: c, text: reasonText(c, o.link), reconnect: true }; }   // #160
  if (o.link?.reason === G.resuming) return { code: G.resuming, text: reasonText(G.resuming, o.link, G.resumingZh) };
  if (o.deferred) return o.deferred;
  if (o.pending) return { code: G.pending, text: BOARD_PENDING_ZH };
  return null;
}
export const gateBannerHtml = (g: Gate, esc: (s: string) => string) => `<b data-gate="${esc(g.code)}">${esc(g.text)}</b> <span class="hint">${esc(G.lockedZh)}</span>${g.reconnect ? ` <button class="btn sm pri" type="button" data-gate-reconnect>${esc(RESUME_TO_F.btnZh)}</button>` : ""}`;
// #160 「重新连接」：后端定义了 op 就发 op，否则断开 ws 重拨
export function gateReconnect(l: { fire(op: string, a?: Record<string, unknown>): void; reconnect(): void }) { if (RESUME_TO_F.op) l.fire(RESUME_TO_F.op); else l.reconnect(); }
// 结果卡：没声明阶跃时长上限 → 明说用了默认值，并给跳到声明的链接
export function durCapNoteHtml(r: any, esc: (s: string) => string): string {
  const t = s(r?.[G.durNotice]); if (!t) return "";
  const k = r?.[G.fixAction] === G.editDecl ? s(r?.[G.fixField]) ?? "" : "";
  return `<p class="rc-durcap warn" id="rc-durcap">${esc(t)}${k ? ` <a href="#" data-decl-unit="${esc(k)}" title="到项目页声明 ${esc(k)}">${esc(G.declZh)}</a>` : ""}</p>`;
}
// 急停中暂不识别何时撤：心跳 hb_flags 里没有「急停」位了（后端同一判据 bit10）；旧固件没 hb_flags → 返回 null，交给急停解除的下降沿
export const estopBitOf = (st: any): boolean | null => Array.isArray(st?.[G.hbFlags]) ? st[G.hbFlags].includes(G.hbEstop) : null;
