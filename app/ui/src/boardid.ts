// 板子身份（握手 board_uid / uid_supported）+ 结构冲突（schema_conflict）阻塞写入。纯逻辑 + 传 root 的 DOM 操作，便于测试
import { BOARD_UID_F, BOARD_UID_ZH, SCHEMA_CONFLICT_F as SC, SCHEMA_CONFLICT_ZH as Z, SCHEMA_CLEAR_F, SCHEMA_FILE_F as SF, SCHEMA_KIND_ZH, SCHEMA_FIX_ZH } from "./fieldmap";
const SCHEMA_CONFLICT_ZH = Z;
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
export type ConflictFile = { path: string; kind: string | null };
export type Conflict = { msg: string; fix: string | null; files: ConflictFile[]; hash: string | null; uid: string | null };
// 两份文件名常常都是 link_schema.json：同名时往上带目录，直到能分开（最多 3 级）
export function distinctName(f: string, all: string[]): string {
  const seg = (p: string) => p.split(/[\\/]/).filter(Boolean);
  const me = seg(f);
  for (let n = 1; n <= 3; n++) { const t = me.slice(-n).join("/"); if (all.filter(o => seg(o).slice(-n).join("/") === t).length <= 1) return n > 1 ? "…/" + t : t; }
  return "…/" + me.slice(-3).join("/");
}
export function conflictOf(x: any): Conflict | null {
  if (!x || typeof x !== "object" || x[SC.resolved] === true) return null;
  const m = typeof x[SC.msg] === "string" && x[SC.msg].trim() ? x[SC.msg] : SCHEMA_CONFLICT_ZH.fallback;
  const f = typeof x[SC.fix] === "string" && x[SC.fix] ? x[SC.fix] : null;
  const fl: ConflictFile[] = (Array.isArray(x[SC.files]) ? x[SC.files] : []).map((v: any): ConflictFile | null =>
    typeof v === "string" && v ? { path: v, kind: null } : v && typeof v === "object" && typeof v[SF.path] === "string" && v[SF.path] ? { path: v[SF.path], kind: typeof v[SF.kind] === "string" ? v[SF.kind] : null } : null).filter(Boolean).slice(0, 2) as ConflictFile[];
  const str = (v: unknown) => typeof v === "string" && v ? v : null;
  return { msg: m, fix: f, files: fl, hash: str(x[SC.hash]), uid: str(x[SC.uid]) };
}
export const fromHello = (h: any) => h && SC.key in h ? { has: true, c: conflictOf(h[SC.key]) } : { has: false, c: null };
export const fromBlockers = (bs: any[] | null | undefined): Conflict | null => conflictOf((bs ?? []).find(b => b?.[SC.code] === SC.key || b?.[SC.codeAlt] === SC.key || b?.[SC.codeAlt2] === SC.key));
export const isClearFix = (c: Conflict | null) => c?.fix === SCHEMA_CLEAR_F.action;
// 横幅：标题 + 原因 + 冲突的两个文件（显示文件名，悬停看完整路径）+ 修复按钮；confirm=true 时换成确认卡
export function conflictBannerHtml(c: Conflict, fix: { kind: string; label: string; note?: string } | null, esc: (s: string) => string, st: "idle" | "confirm" | "busy" | "fail" = "idle") {
  const files = c.files.length ? ` <span class="sconf-files">${esc(Z.files)}：${c.files.map(f => `${f.kind ? `<span class="sconf-kind k-${esc(f.kind)}" data-kind="${esc(f.kind)}">${esc(SCHEMA_KIND_ZH[f.kind] ?? f.kind)}</span>` : ""}<code title="${esc(f.path)}">${esc(distinctName(f.path, c.files.map(x => x.path)))}</code>`).join(" ↔ ")}</span>` : "";
  let btn = "";
  if (isClearFix(c)) btn = st === "confirm" ? `<span class="sconf-confirm" data-sconf-confirm><span>${esc(Z.confirm)}</span> <button class="btn sm pri" type="button" data-sconf-ok>${esc(Z.ok)}</button><button class="btn sm" type="button" data-sconf-cancel>${esc(Z.cancel)}</button></span>`
    : st === "busy" ? `<span class="hint">${esc(Z.busy)}</span>`
    : `<button class="btn sm pri" type="button" data-sconf-clear>${esc(Z.clear)}</button>${st === "fail" ? ` <span>${esc(Z.fail)}</span>` : ""}`;
  else if (c.fix && fix) btn = fix.kind === "run" ? `<button class="btn sm pri" type="button" data-sc-conflict-fix="${esc(c.fix)}">${esc(SCHEMA_FIX_ZH[c.fix] ?? fix.label)}</button>` : `<button class="btn sm" type="button" disabled title="${esc(fix.note ?? "")}">${esc(fix.label)}</button>`;
  return `<b>${esc(Z.title)}</b> <span>${esc(c.msg)}</span>${files} ${btn}`;
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
// op clear_schema_cache 的参数与回执
export const clearArgs = (c: Conflict) => c.hash ? { [SCHEMA_CLEAR_F.hash]: c.hash } : {};
export function clearResult(r: any): { ok: boolean; removed: string[] } {
  const rm = Array.isArray(r?.[SCHEMA_CLEAR_F.removed]) ? r[SCHEMA_CLEAR_F.removed].filter((v: unknown) => typeof v === "string") : [];
  return { ok: r?.[SCHEMA_CLEAR_F.ok] === true, removed: rm };
}
export const removedZh = (n: number) => Z.removed.replace("N", String(n));
