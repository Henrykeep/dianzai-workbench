import { ESTOP_F, ESTOP_CAUSES, ESTOP_GENERIC_ZH, ESTOP_GAP_UNKNOWN_ZH, ESTOP_HB_ZH } from "./fieldmap";
// 急停提示（问题池 #25 / #28）。来源由本地服务在事件里给 source：heartbeat_lost | firmware:<cause> | ui | selftest。
// 前三种用固定文案；firmware:<cause> 优先用 status.estop_cause.message_zh；都没有时写「急停已触发，原因未上报」，详情给最近一次心跳时间。
// 心跳超时（watchdog 事件）与急停分开提示，不混成一句。
export type EstopCause = { cause?: string; message_zh?: string } | null | undefined;
export type EstopEv = { kind?: string; source?: string; text?: string };
export const SOURCE_TEXT: Record<string, string> = {
  heartbeat_lost: "急停：板子收不到上位机心跳，已自动停车",
  ui: "急停：在工作台上按了急停（按钮 / Esc / 空格）",
  selftest: "急停：上电自检未通过，板子拒绝运行",
};
export const UNREPORTED = "急停已触发，原因未知（重连后未上报）";
// #41：重连后 cause 可能是 null / "null" / 空串——一律显示「原因未知（重连后未上报）」，不把 null 漏到界面上
export const CAUSE_UNKNOWN = "原因未知（重连后未上报）";
const blank = (v: unknown) => v == null || (typeof v === "string" && (!v.trim() || /^(null|undefined|none)$/i.test(v.trim())));
export const causeText = (v: unknown) => blank(v) ? CAUSE_UNKNOWN : String(v);
const hhmmss = (ms: number) => new Date(ms).toLocaleTimeString("zh-CN", { hour12: false });
export function estopView(ev: EstopEv | undefined, cause: EstopCause, lastHbMs?: number | null): { head: string; detail: string } {
  const src = ev?.source ?? "";
  const hb = lastHbMs ? `最近一次心跳 ${hhmmss(lastHbMs)}` : "最近一次心跳：未收到";
  if (SOURCE_TEXT[src]) return { head: SOURCE_TEXT[src], detail: hb };
  if (src.startsWith("firmware:")) {
    const c = src.slice(9);
    if (!blank(cause?.message_zh)) return { head: cause!.message_zh!, detail: hb };
    return { head: blank(c) ? `急停：固件报告停车，${CAUSE_UNKNOWN}` : `急停：固件报告停车（原因码 ${c}），本地服务未给出说明`, detail: hb };
  }
  if (!blank(cause?.message_zh)) return { head: cause!.message_zh!, detail: hb };
  return { head: UNREPORTED, detail: hb };
}
// 心跳超时单独一行
export const watchdogText = (ev: EstopEv) => `心跳超时：${ev.text || "板子心跳中断"}`;
// 锁存只认本地服务上报（status.tx_locked）；本地服务断开时保留最后一次上报值，前端不自行清除（#20）
export function latchedOf(st: { tx_locked?: boolean } | undefined, prev: boolean, sidecarUp: boolean): boolean {
  if (!sidecarUp) return prev;
  return typeof st?.tx_locked === "boolean" ? st.tx_locked : prev;
}

// 横幅一行：「[HH:MM ]<原因>[ <实测> ms（阈值 <阈值> ms）|（间隔未知）]，已锁存」；缺的字段整段省略（#132）
const pick = (os: any[], ks: readonly string[]) => { for (const o of os) for (const k of ks) { const v = o?.[k]; if (v != null && v !== "") return v; } return undefined; };
const hhmm = (t: number) => { const d = new Date(t); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
export function estopRestored(...os: any[]): boolean { return os.some(o => o?.[ESTOP_F.restored] === true || o?.[ESTOP_F.source] === ESTOP_F.restoredSrc); }
export function estopCause(ev: any, status: any): string {
  const c = status?.estop_cause;
  for (const v of [ev?.[ESTOP_F.code], status?.estop?.[ESTOP_F.code], c?.[ESTOP_F.code], ev?.[ESTOP_F.source], ev?.kind, typeof c === "string" ? c : c?.cause, c?.code]) {
    const k = typeof v === "string" ? v.replace(/^firmware:/, "") : typeof v === "number" ? String(v) : "";
    if (k && k !== ESTOP_F.restoredSrc && k !== "estop" && ESTOP_CAUSES[k]) return k;
  }
  return "";
}
// #119 锁存时刻只认后端 latched_at（ms / s / ISO 串）；没有就不写时间（#132），不拿页面看到的时刻冒充
export function latchTime(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v < 1e12 ? v * 1000 : v;
  if (typeof v === "string" && v.trim()) { const t = Date.parse(v); return Number.isFinite(t) ? t : null; }
  return null;
}
// #132：缺值最多一句「（间隔未知）」；手动急停只「HH:MM 手动急停，已锁存」
export function estopLine(ev: any, status: any): { line: string; restored: boolean; cause: string; fix: string } {
  const os = [ev, status?.estop, status, status?.estop_cause], restored = estopRestored(...os), cause = estopCause(ev, status), spec = ESTOP_CAUSES[cause];
  const t = latchTime(pick(os, ESTOP_F.at));
  const r0 = pick(os, ESTOP_F.reason), f = spec?.fields ?? [];
  const reason = spec?.label ?? (typeof r0 === "string" && r0.trim() ? r0.trim() : f.length ? ESTOP_HB_ZH : ESTOP_GENERIC_ZH);
  const ms = (v: unknown) => typeof v === "number" && Number.isFinite(v) ? `${Math.round(v)} ms` : "";
  let tail = "";
  if (f.includes("measured")) {   // 实测有 → 「1601 ms」，阈值有才加「（阈值 1500 ms）」；实测没有 → 只一句「（间隔未知）」
    const m = ms(pick(os, ESTOP_F.measured)), th = f.includes("threshold") ? ms(pick(os, ESTOP_F.threshold)) : "";
    tail = m ? ` ${m}${th ? `（阈值 ${th}）` : ""}` : ESTOP_GAP_UNKNOWN_ZH;
  }
  const fx = pick(os, [ESTOP_F.fix]);
  return { restored, cause, fix: typeof fx === "string" ? fx : "", line: `${t != null ? hhmm(t) + " " : ""}${reason}${tail}，已锁存` };
}
// 解除两步：第一次点 → 「确认解除？」+「取消」，再点才发；5 s 不点自动退回
export const CLEAR_CONFIRM_MS = 5000;
export function clearStep(state: "idle" | "confirm", click: "clear" | "cancel" | "timeout"): { state: "idle" | "confirm"; send: boolean } {
  if (click === "clear") return state === "confirm" ? { state: "idle", send: true } : { state: "confirm", send: false };
  return { state: "idle", send: false };
}
