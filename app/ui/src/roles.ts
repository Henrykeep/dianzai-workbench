// 参数角色确认（confirm_roles）：纯逻辑 + HTML，字段名只走 fieldmap
import { roleCodes, roleCodesNotice } from "./rolecodes";
import { SELFCHECK_BTN_HTML } from "./selfcheck";
import { ROLE_F, ROLE_SUGGEST_ZH, ROLE_BTN_ZH, ROLE_RETRY_ZH, ROLE_SENDING_ZH, ROLE_REPLY_F, ROLE_NO_FLASH_ZH, ROLE_LIM_ZH, MISSING_ZH, ROLE_PREVIEW_F as PV, ROLE_ERR_F as RE, ROLE_PREVIEW_ZH, ROLE_COMMIT_ZH, ROLE_CANCEL_ZH, ROLE_PROTECT_ZH } from "./fieldmap";
export type RoleReq = { missing: string[]; suggested: Record<string, string>; reason: string };
const CODES = { has: (c: unknown) => roleCodes().some(x => x[0] === c) };
export const roleLabel = (c: unknown) => roleCodes().find(x => x[0] === c)?.[1] ?? "";
export function toRoleReq(m: any): RoleReq | null {
  for (const o of [m, m?.result, m?.error, m?.err]) {
    if (!o || (o[ROLE_F.fix] !== ROLE_F.confirm && o[ROLE_F.code] !== ROLE_F.unconfirmed)) continue;
    const missing = Array.isArray(o[ROLE_F.missing]) ? o[ROLE_F.missing].filter((x: unknown) => typeof x === "string") : [];
    const sg = o[ROLE_F.suggested] && typeof o[ROLE_F.suggested] === "object" ? o[ROLE_F.suggested] : {};
    const suggested: Record<string, string> = {};
    for (const k of missing) if (CODES.has(sg[k])) suggested[k] = sg[k];
    return { missing, suggested, reason: typeof o[ROLE_F.reason] === "string" ? o[ROLE_F.reason] : typeof o[ROLE_F.msg] === "string" ? o[ROLE_F.msg] : "" };   // reason_zh 原样显示
  }
  return null;
}
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" } as any)[c]);
// 参数行里的角色位：待确认 → 下拉（建议值预选 + 「建议，待确认」）；否则握手给了 role → 只读
export function roleCellHtml(name: string, req: RoleReq | null, hsRole?: unknown, picked: Record<string, string> = {}): string {
  if (req?.missing.includes(name)) {
    const sg = picked[name] || req.suggested[name];   // 已选的优先：参数列表重画不丢用户的选择
    const opts = `<option value=""${sg ? "" : " selected"} disabled>选角色</option>` + roleCodes().map(([c, zh]) => `<option value="${c}"${c === sg ? " selected" : ""}>${zh}</option>`).join("");
    return `<span class="role-pick"><select class="role-sel" data-role-n="${esc(name)}" aria-label="${esc(name)} 角色">${opts}</select>${sg ? `<span class="role-sg">${ROLE_SUGGEST_ZH}</span>` : ""}${sg === "LIM" ? `<span class="role-lim">${ROLE_LIM_ZH}</span>` : ""}</span>`;
  }
  const l = roleLabel(hsRole);
  return l ? `<span class="role-ro" title="角色（握手参数表）">${l}</span>` + (hsRole === "LIM" ? `<span class="role-lim">${ROLE_LIM_ZH}</span>` : "") : "";
}
// #135 卡状态：idle（缺几个就灰着 + 提示）→ sending（立刻灰，只发一次）→ sent（{ok, roles}）/ error（message_zh 原文，可再点）
export type RolePreview = { changeId: unknown; diff: string; target: string; copyFrom: string; msg: string; roles: Record<string, string> };
export type RoleUi = { phase: "idle" | "sending" | "preview" | "committing" | "sent" | "error"; left: number; msg?: string; same?: boolean; fix?: string; protect?: boolean; preview?: RolePreview };
export const ROLE_REJECT_ZH = "后端拒绝：";
export const roleLeftZh = (n: number) => `还有 ${n} 个参数未选角色`;
export function roleCardHtml(req: RoleReq | null, st: RoleUi | boolean = { phase: "idle", left: 0 }): string {
  if (!req) return "";
  const s: RoleUi = typeof st === "boolean" ? { phase: st ? "sent" : "idle", left: 0 } : st;
  if ((s.phase === "preview" || s.phase === "committing") && s.preview) return roleConfirmHtml(s.preview, s.phase === "committing");
  const btn = s.phase === "sent" ? `<button class="btn" id="role-retry">${ROLE_RETRY_ZH}</button>`
    : `<button class="btn primary" id="role-ok"${s.phase === "sending" || s.left > 0 || (s.phase === "error" && s.same !== false) ? " disabled" : ""}>${s.phase === "sending" ? ROLE_SENDING_ZH : ROLE_BTN_ZH}</button>` +
      (s.left > 0 && s.phase !== "sending" ? `<span class="role-left">${roleLeftZh(s.left)}</span>` : s.phase === "error" && s.same !== false ? `<span class="role-left">请修改角色后再确认</span>` : "");
  return `<div class="card role-card" id="role-card"><b>需要确认参数角色</b><p class="role-why">${esc(req.reason || MISSING_ZH)}</p>` +
    `<p class="role-nf">${ROLE_NO_FLASH_ZH}</p>${roleCodesNotice() ? `<p class="role-data warn-t" id="role-data">${esc(roleCodesNotice())} ${SELFCHECK_BTN_HTML}</p>` : ""}<p>待确认：${req.missing.map(esc).join("、") || MISSING_ZH}</p>` +
    (s.phase === "error" && s.msg ? `<p class="role-err" id="role-err">${s.protect ? `<b>${ROLE_PROTECT_ZH}</b> ` : ""}${esc(s.msg)}${s.fix ? `<br><span class="role-fix">处理：${esc(s.fix)}</span>` : ""}</p>` : "") +
    (s.phase === "sent" && s.msg ? `<p class="role-ok-t">${esc(s.msg)}</p>` : "") + btn + `</div>`;
}
// 预览确认卡：diff 逐行着色，写到哪（target）、从哪复制（copy_from）；点「确认写入」才带 change_id 发 confirmed
export function diffHtml(d: string): string {
  return d.split("\n").map(l => `<span class="${l.startsWith("+") && !l.startsWith("+++") ? "dl-add" : l.startsWith("-") && !l.startsWith("---") ? "dl-del" : l.startsWith("@@") ? "dl-hunk" : "dl-ctx"}">${esc(l)}</span>`).join("\n");
}
export function roleConfirmHtml(p: RolePreview, busy = false): string {
  return `<div class="card role-card role-confirm" id="role-card"><b>${ROLE_PREVIEW_ZH}</b>${p.msg ? `<p class="role-why">${esc(p.msg)}</p>` : ""}` +
    `<p class="role-tgt">写入：<code>${esc(p.target || MISSING_ZH)}</code>${p.copyFrom ? `<br>先从 <code>${esc(p.copyFrom)}</code> 复制到工程目录` : ""}</p>` +
    `<pre class="role-diff" id="role-diff">${diffHtml(p.diff)}</pre>` +
    `<button class="btn primary" id="role-commit"${busy ? " disabled" : ""}>${busy ? ROLE_SENDING_ZH : ROLE_COMMIT_ZH}</button> <button class="btn" id="role-cancel"${busy ? " disabled" : ""}>${ROLE_CANCEL_ZH}</button></div>`;
}
// 缺几个：没在下拉里选、也没有合法建议的
export const roleLeft = (req: RoleReq, picked: Record<string, string>) => req.missing.filter(n => !CODES.has(picked[n] ?? req.suggested[n])).length;
// 回执：{ok:true, roles} → sent；否则 message_zh 原文（没给就「后端未给」）
export function roleReply(r: any, roles: Record<string, string> = {}): RoleUi {
  const str = (v: unknown) => typeof v === "string" && v ? v : "";
  if (r && r[PV.needs] === true && r[PV.changeId] != null) return { phase: "preview", left: 0, preview: { changeId: r[PV.changeId], diff: str(r[PV.diff]), target: str(r[PV.target]), copyFrom: str(r[PV.copyFrom]), msg: str(r[PV.msg]), roles } };
  if (r && r[ROLE_REPLY_F.ok] === true) return str(r[PV.msg]) ? { phase: "sent", left: 0, msg: str(r[PV.msg]) } : { phase: "sent", left: 0 };
  const m = r && (str(r[RE.reasonZh]) || str(r[RE.msgZh]) || str(r[RE.msg])) || MISSING_ZH;   // 不静默：后端原文
  const u: RoleUi = { phase: "error", left: 0, msg: ROLE_REJECT_ZH + m, same: true }; const fx = r ? str(r[RE.fix]) : ""; if (fx) u.fix = fx; if (r?.[RE.code] === RE.protect) u.protect = true; return u;
}
// 回传英文代码；有一个没选就返回 null
export function collectRoles(req: RoleReq, picked: Record<string, string>): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const n of req.missing) { const c = picked[n] ?? req.suggested[n]; if (!CODES.has(c)) return null; out[n] = c; }
  return out;
}

// #142 只发一次：发送中不发；回错后角色没变不重发（按钮置灰直到改选）
export const rolesKey = (r: Record<string, string>) => JSON.stringify(Object.keys(r).sort().map(k => [k, r[k]]));
export class RoleSender {
  last: string | null = null; busy = false;
  canSend(roles: Record<string, string>) { return !this.busy && rolesKey(roles) !== this.last; }
  async send(roles: Record<string, string>, call: (r: Record<string, string>) => Promise<any>): Promise<RoleUi | null> {
    if (!this.canSend(roles)) return null;
    this.busy = true; this.last = rolesKey(roles);
    try { const r = await call(roles).catch((e: any) => e ?? {}); const u = roleReply(r, roles); if (u.phase === "sent") this.last = null; return u; }
    finally { this.busy = false; }
  }
  // 第二步：只有人点了「确认写入」才发；change_id 一次性，发过就清掉
  async commit(p: RolePreview, call: (args: Record<string, unknown>) => Promise<any>): Promise<RoleUi | null> {
    if (this.busy) return null; this.busy = true;
    try { const r = await call({ roles: p.roles, [PV.confirmed]: true, [PV.changeId]: p.changeId }).catch((e: any) => e ?? {}); const u = roleReply(r, p.roles); if (u.phase !== "error") this.last = null; return u; }
    finally { this.busy = false; }
  }
  reset() { this.last = null; this.busy = false; }
}
