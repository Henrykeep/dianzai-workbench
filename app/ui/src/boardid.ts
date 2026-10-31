// 板子身份（握手 board_uid / uid_supported）+ 结构冲突（schema_conflict）阻塞写入。纯逻辑 + 传 root 的 DOM 操作，便于测试
import { BOARD_UID_F, BOARD_UID_ZH, SCHEMA_CONFLICT_F as SC, SCHEMA_CONFLICT_ZH } from "./fieldmap";
import { WRITE_SEL } from "./batch1";
export type BoardId = { uid: string | null; supported: boolean; notice: string; short: string };
const HEX16 = /^[0-9a-f]{16}$/i;
// 握手没带这两个字段 → null（旧本地服务，不提示）
export function boardIdOf(hs: any): BoardId | null {
  if (!hs || typeof hs !== "object" || !(BOARD_UID_F.supported in hs || BOARD_UID_F.uid in hs)) return null;
  const raw = hs[BOARD_UID_F.uid], uid = typeof raw === "string" && HEX16.test(raw) ? raw.toLowerCase() : null;
  const supported = hs[BOARD_UID_F.supported] === true;
  if (!supported) return { uid: null, supported: false, notice: BOARD_UID_ZH.unsupported, short: "" };
  return { uid, supported: true, notice: uid ? "" : BOARD_UID_ZH.unread, short: uid ? shortUid(uid) : "" };
}
export const shortUid = (u: string) => u.length > 8 ? `${u.slice(0, 4)}…${u.slice(-4)}` : u;
// 换板判定：只有两边都有 uid 才能说同一块；不支持 / 未读到 → 永远不算同一块（null = 不知道）
export function sameBoard(a: BoardId | null, b: BoardId | null): boolean | null {
  if (!a?.uid || !b?.uid || !a.supported || !b.supported) return null;
  return a.uid === b.uid;
}
export const uidChipHtml = (b: BoardId | null, esc: (s: string) => string) =>
  !b ? "" : b.uid ? `<span class="uid-chip mono" title="板子身份 ${esc(b.uid)}">板 ${esc(b.short)}</span>` : `<span class="uid-chip warn-t" data-uid-notice>${esc(b.notice)}</span>`;
// 结构冲突：返回 {msg, fix} 或 null（已解决）
export type Conflict = { msg: string; fix: string | null };
export function conflictOf(x: any): Conflict | null {
  if (!x || typeof x !== "object" || x[SC.resolved] === true) return null;
  const m = typeof x[SC.msg] === "string" && x[SC.msg].trim() ? x[SC.msg] : SCHEMA_CONFLICT_ZH.fallback;
  const f = typeof x[SC.fix] === "string" && x[SC.fix] ? x[SC.fix] : null;
  return { msg: m, fix: f };
}
export const fromHello = (h: any) => h && SC.key in h ? { has: true, c: conflictOf(h[SC.key]) } : { has: false, c: null };
export const fromBlockers = (bs: any[] | null | undefined): Conflict | null => conflictOf((bs ?? []).find(b => b?.[SC.code] === SC.key || b?.[SC.codeAlt] === SC.key));
export function conflictBannerHtml(c: Conflict, fix: { kind: string; label: string; note?: string } | null, esc: (s: string) => string) {
  const btn = !c.fix || !fix ? "" : fix.kind === "run" ? `<button class="btn sm" type="button" data-sc-conflict-fix="${esc(c.fix)}">${esc(fix.label)}</button>` : `<button class="btn sm" type="button" disabled title="${esc(fix.note ?? "")}">${esc(fix.label)}</button>`;
  return `<b>${esc(SCHEMA_CONFLICT_ZH.title)}</b> <span>${esc(c.msg)}</span> ${btn}`;
}
// 写参数 + 提交卡的「确认提交」（取消仍可点）
export const SCHEMA_LOCK_SEL = WRITE_SEL + ',button[data-cc="ok"]';
// 写入禁用：与急停锁存分开记账（data-sconf），两者互不解开对方
export function lockSchemaIn(root: ParentNode, on: boolean) {
  if (on) root.querySelectorAll<any>(SCHEMA_LOCK_SEL).forEach(e => { if (!e.dataset.sconf) { e.dataset.sconfTitle = e.title || ""; e.dataset.sconf = e.disabled ? "was" : "1"; } e.disabled = true; e.title = SCHEMA_CONFLICT_ZH.why; });
  else root.querySelectorAll<any>("[data-sconf]").forEach(e => { e.disabled = e.dataset.sconf === "was" || !!e.dataset.estop; e.title = e.dataset.estop ? e.title : e.dataset.sconfTitle ?? ""; delete e.dataset.sconf; delete e.dataset.sconfTitle; });
}
// 结果卡是否属于当前板：旧本地服务（无字段）→ 按端口；不支持 / 未读到身份 → 一律不算同一块；结果带 board_uid → 按身份比，否则按端口
export function resultSameBoard(res: any, portSame: boolean, cur: BoardId | null): boolean {
  if (!cur) return portSame;
  if (!cur.supported || !cur.uid) return false;
  const r = res?.[BOARD_UID_F.uid];
  return typeof r === "string" && HEX16.test(r) ? r.toLowerCase() === cur.uid : portSame;
}
