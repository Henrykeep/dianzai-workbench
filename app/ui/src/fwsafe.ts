// r10w fw_estop_unsafe：阻断横幅 + 「重新烧录」（走现有烧录入口）+ 禁用驱动执行器的控件（读取、存参数、烧录仍可用）
import { FW_ESTOP_F as F, FW_ESTOP_ZH as Z } from "./fieldmap";
import { WRITE_SEL } from "./batch1";
export type FwUnsafe = { msg: string; fix: string; min: string | null; ver: string | null };
const str = (v: unknown) => typeof v === "string" && v ? v : null;
// 事件 / error 回包 / 阻塞项都能认；safe:true → null（已解除）
export function fwUnsafeOf(x: any): FwUnsafe | null {
  if (!x || typeof x !== "object") return null;
  const hit = x.type === F.key || x[F.code] === F.key || x[F.reason] === F.key || x.blocker_code === F.key;
  if (!hit || x[F.safe] === true) return null;
  return { msg: str(x[F.msg]) ?? str(x.message) ?? Z.fallback, fix: str(x[F.fix]) ?? "reflash", min: str(x[F.min]), ver: str(x[F.ver]) };
}
export const fromBlockersFw = (bs: any[] | null | undefined) => { for (const b of bs ?? []) { const u = fwUnsafeOf(b); if (u) return u; } return null; };
// 驱动执行器的控件 = 写入控件减去：烧录（fw-flash）、存 flash（tb-save）、读黑匣子（pre-bbtn）
export const KEEP_IDS = ["fw-flash", "tb-save", "pre-bbtn", "fw-build"];
export const ACTUATE_SEL = WRITE_SEL.split(",").filter(s => !KEEP_IDS.some(k => s.trim() === "#" + k)).join(",") + ",#seal-selftest,#sp-restore";
export function lockActuateIn(root: ParentNode, on: boolean, why: string = Z.why) {
  if (on) root.querySelectorAll<any>(ACTUATE_SEL).forEach(e => { if (!e.dataset.fwsafe) { e.dataset.fwsafeTitle = e.title || ""; e.dataset.fwsafe = e.disabled ? "was" : "1"; } e.disabled = true; e.title = why; });
  else root.querySelectorAll<any>("[data-fwsafe]").forEach(e => { e.disabled = e.dataset.fwsafe === "was" || !!e.dataset.estop || !!e.dataset.sconf; e.title = e.dataset.fwsafeTitle ?? ""; delete e.dataset.fwsafe; delete e.dataset.fwsafeTitle; });
}
export function fwBannerHtml(u: FwUnsafe, esc: (s: string) => string): string {
  const v = u.min ? `${Z.min} ${u.min}${u.ver ? ` · 当前 ${u.ver}` : ""}` : "";   // 版本放悬停：横幅保持一行，不压住页头
  return `<b title="${esc(v)}">${esc(u.msg)}</b> <button class="btn sm pri" type="button" data-fwsafe-fix="${esc(u.fix)}" title="${esc(v)}">${esc(Z.btn)}</button>`;
}
