// 参数角色确认（confirm_roles）：纯逻辑 + HTML，字段名只走 fieldmap
import { ROLE_F, ROLE_CODES, ROLE_SUGGEST_ZH, ROLE_BTN_ZH, ROLE_RETRY_ZH, ROLE_NO_FLASH_ZH, ROLE_LIM_ZH, MISSING_ZH } from "./fieldmap";
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
export function roleCellHtml(name: string, req: RoleReq | null, hsRole?: unknown): string {
  if (req?.missing.includes(name)) {
    const sg = req.suggested[name];
    const opts = `<option value=""${sg ? "" : " selected"} disabled>选角色</option>` + ROLE_CODES.map(([c, zh]) => `<option value="${c}"${c === sg ? " selected" : ""}>${zh}</option>`).join("");
    return `<span class="role-pick"><select class="role-sel" data-role-n="${esc(name)}" aria-label="${esc(name)} 角色">${opts}</select>${sg ? `<span class="role-sg">${ROLE_SUGGEST_ZH}</span>` : ""}${sg === "LIM" ? `<span class="role-lim">${ROLE_LIM_ZH}</span>` : ""}</span>`;
  }
  const l = roleLabel(hsRole);
  return l ? `<span class="role-ro" title="角色（握手参数表）">${l}</span>` + (hsRole === "LIM" ? `<span class="role-lim">${ROLE_LIM_ZH}</span>` : "") : "";
}
export function roleCardHtml(req: RoleReq | null, sent = false): string {
  if (!req) return "";
  return `<div class="card role-card" id="role-card"><b>需要确认参数角色</b><p class="role-why">${esc(req.reason || MISSING_ZH)}</p>` +
    `<p class="role-nf">${ROLE_NO_FLASH_ZH}</p><p>待确认：${req.missing.map(esc).join("、") || MISSING_ZH}</p>` +
    (sent ? `<button class="btn" id="role-retry">${ROLE_RETRY_ZH}</button>` : `<button class="btn primary" id="role-ok">${ROLE_BTN_ZH}</button>`) + `</div>`;
}
// 回传英文代码；有一个没选就返回 null
export function collectRoles(req: RoleReq, picked: Record<string, string>): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const n of req.missing) { const c = picked[n] ?? req.suggested[n]; if (!CODES.has(c)) return null; out[n] = c; }
  return out;
}
