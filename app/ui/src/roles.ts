// 参数角色确认（confirm_roles）：纯逻辑 + HTML，字段名只走 fieldmap
import { ROLE_F, ROLE_CODES, ROLE_SUGGEST_ZH, ROLE_BTN_ZH, ROLE_RETRY_ZH, ROLE_SENDING_ZH, ROLE_REPLY_F, ROLE_NO_FLASH_ZH, ROLE_LIM_ZH, MISSING_ZH } from "./fieldmap";
export type RoleReq = { missing: string[]; suggested: Record<string, string>; reason: string };
const CODES = new Set<string>(ROLE_CODES.map(c => c[0]));
export const roleLabel = (c: unknown) => ROLE_CODES.find(x => x[0] === c)?.[1] ?? "";
export function toRoleReq(m: any): RoleReq | null {
  for (const o of [m, m?.result, m?.error, m?.err]) {
    if (!o || o[ROLE_F.fix] !== ROLE_F.confirm) continue;
    const missing = Array.isArray(o[ROLE_F.missing]) ? o[ROLE_F.missing].filter((x: unknown) => typeof x === "string") : [];
    const sg = o[ROLE_F.suggested] && typeof o[ROLE_F.suggested] === "object" ? o[ROLE_F.suggested] : {};
    const suggested: Record<string, string> = {};
    for (const k of missing) if (CODES.has(sg[k])) suggested[k] = sg[k];
    return { missing, suggested, reason: typeof o[ROLE_F.reason] === "string" ? o[ROLE_F.reason] : "" };   // reason_zh 原样显示
  }
  return null;
}
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" } as any)[c]);
// 参数行里的角色位：待确认 → 下拉（建议值预选 + 「建议，待确认」）；否则握手给了 role → 只读
export function roleCellHtml(name: string, req: RoleReq | null, hsRole?: unknown, picked: Record<string, string> = {}): string {
  if (req?.missing.includes(name)) {
    const sg = picked[name] || req.suggested[name];   // 已选的优先：参数列表重画不丢用户的选择
    const opts = `<option value=""${sg ? "" : " selected"} disabled>选角色</option>` + ROLE_CODES.map(([c, zh]) => `<option value="${c}"${c === sg ? " selected" : ""}>${zh}</option>`).join("");
    return `<span class="role-pick"><select class="role-sel" data-role-n="${esc(name)}" aria-label="${esc(name)} 角色">${opts}</select>${sg ? `<span class="role-sg">${ROLE_SUGGEST_ZH}</span>` : ""}${sg === "LIM" ? `<span class="role-lim">${ROLE_LIM_ZH}</span>` : ""}</span>`;
  }
  const l = roleLabel(hsRole);
  return l ? `<span class="role-ro" title="角色（握手参数表）">${l}</span>` + (hsRole === "LIM" ? `<span class="role-lim">${ROLE_LIM_ZH}</span>` : "") : "";
}
// #135 卡状态：idle（缺几个就灰着 + 提示）→ sending（立刻灰，只发一次）→ sent（{ok, roles}）/ error（message_zh 原文，可再点）
export type RoleUi = { phase: "idle" | "sending" | "sent" | "error"; left: number; msg?: string; same?: boolean };
export const ROLE_REJECT_ZH = "后端拒绝：";
export const roleLeftZh = (n: number) => `还有 ${n} 个参数未选角色`;
export function roleCardHtml(req: RoleReq | null, st: RoleUi | boolean = { phase: "idle", left: 0 }): string {
  if (!req) return "";
  const s: RoleUi = typeof st === "boolean" ? { phase: st ? "sent" : "idle", left: 0 } : st;
  const btn = s.phase === "sent" ? `<button class="btn" id="role-retry">${ROLE_RETRY_ZH}</button>`
    : `<button class="btn primary" id="role-ok"${s.phase === "sending" || s.left > 0 || (s.phase === "error" && s.same !== false) ? " disabled" : ""}>${s.phase === "sending" ? ROLE_SENDING_ZH : ROLE_BTN_ZH}</button>` +
      (s.left > 0 && s.phase !== "sending" ? `<span class="role-left">${roleLeftZh(s.left)}</span>` : s.phase === "error" && s.same !== false ? `<span class="role-left">请修改角色后再确认</span>` : "");
  return `<div class="card role-card" id="role-card"><b>需要确认参数角色</b><p class="role-why">${esc(req.reason || MISSING_ZH)}</p>` +
    `<p class="role-nf">${ROLE_NO_FLASH_ZH}</p><p>待确认：${req.missing.map(esc).join("、") || MISSING_ZH}</p>` +
    (s.phase === "error" && s.msg ? `<p class="role-err">${esc(s.msg)}</p>` : "") + btn + `</div>`;
}
// 缺几个：没在下拉里选、也没有合法建议的
export const roleLeft = (req: RoleReq, picked: Record<string, string>) => req.missing.filter(n => !CODES.has(picked[n] ?? req.suggested[n])).length;
// 回执：{ok:true, roles} → sent；否则 message_zh 原文（没给就「后端未给」）
export function roleReply(r: any): RoleUi {
  if (r && r[ROLE_REPLY_F.ok] === true) return { phase: "sent", left: 0 };
  const m = r && typeof r[ROLE_REPLY_F.msg] === "string" && r[ROLE_REPLY_F.msg] ? r[ROLE_REPLY_F.msg] : MISSING_ZH;
  return { phase: "error", left: 0, msg: ROLE_REJECT_ZH + m, same: true };
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
    try { const r = await call(roles).catch((e: any) => ({ message_zh: e?.message_zh ?? e?.message })); const u = roleReply(r); if (u.phase === "sent") this.last = null; return u; }
    finally { this.busy = false; }
  }
  reset() { this.last = null; this.busy = false; }
}
