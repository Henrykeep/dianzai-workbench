import { ESTOP_F, MISSING_ZH, ESTOP_CAUSES } from "./fieldmap";
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

// r9f 横幅一行：「<HH:MM> <reason_zh> <measured> ms（阈值 <threshold> ms），已锁存」；缺字段写「后端未给」
const pick = (os: any[], ks: readonly string[]) => { for (const o of os) for (const k of ks) { const v = o?.[k]; if (v != null && v !== "") return v; } return undefined; };
const hhmm = (t: number) => { const d = new Date(t); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
export function estopRestored(...os: any[]): boolean { return os.some(o => o?.[ESTOP_F.restored] === true || o?.[ESTOP_F.source] === ESTOP_F.restoredSrc); }
// localAt：界面自己看到锁存的时刻；从上次恢复的锁存不用它（那不是锁存发生的时刻）
export function estopCause(ev: any, status: any): string {
  const c = status?.estop_cause;
  for (const v of [ev?.[ESTOP_F.source], ev?.kind, typeof c === "string" ? c : c?.cause]) {
    const k = typeof v === "string" ? v.replace(/^firmware:/, "") : "";
    if (k && k !== ESTOP_F.restoredSrc && k !== "estop" && ESTOP_CAUSES[k]) return k;
  }
  return "";
}
export function estopLine(ev: any, status: any, localAt: number | null): { line: string; restored: boolean; cause: string } {
  const os = [ev, status, status?.estop_cause], restored = estopRestored(...os), cause = estopCause(ev, status), spec = ESTOP_CAUSES[cause];
  const at = pick(os, ESTOP_F.at), t = typeof at === "number" && Number.isFinite(at) ? at : restored ? null : localAt;
  const r0 = pick(os, ESTOP_F.reason), reason = spec?.label ?? (typeof r0 === "string" && r0.trim() ? r0.trim() : MISSING_ZH);
  const n = (v: unknown) => typeof v === "number" && Number.isFinite(v) ? `${Math.round(v)}` : MISSING_ZH;
  const f = spec?.fields ?? [];
  const nums = f.length ? ` ${f.includes("measured") ? n(pick(os, ESTOP_F.measured)) + " ms" : ""}${f.includes("threshold") ? `（阈值 ${n(pick(os, ESTOP_F.threshold))} ms）` : ""}` : "";
  return { restored, cause, line: `${t != null ? hhmm(t) : MISSING_ZH} ${reason}${nums}，已锁存` };
}
// 解除两步：第一次点 → 「确认解除？」+「取消」，再点才发；5 s 不点自动退回
export const CLEAR_CONFIRM_MS = 5000;
export function clearStep(state: "idle" | "confirm", click: "clear" | "cancel" | "timeout"): { state: "idle" | "confirm"; send: boolean } {
  if (click === "clear") return state === "confirm" ? { state: "idle", send: true } : { state: "confirm", send: false };
  return { state: "idle", send: false };
}
