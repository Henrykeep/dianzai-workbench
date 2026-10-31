// r41b：急停在时间线 / 曲线 / 调参页上的显示（纯函数，main.ts 接线）
// - 时间线：优先 cause_zh（本地服务 8660bda 起拆成 cause_zh + fix_hint_zh）；旧字段 message_zh 去掉末尾 R 与「确认安全后点"解除急停"R」提示
// - 已解除的急停 = 历史：中性灰标签，不用红
// - fix_hint_zh 只在锁存中的告警条里出现
// - 解除后：灰色记录写明设定值已清零；调参页给「恢复急停前目标」次级按钮，只在点击时下发，从不自动
export type EstopEvLike = { kind: string; text?: string; cause_zh?: string | null; message_zh?: string | null; fix_hint_zh?: string | null };
const HINT_RE = /[，,；;。→\s]*确认安全后点\s*[“"「]?解除急停\s*R?[”"」]?\s*R?\s*[。.]?\s*$/;
export function stripLegacy(s: string): string {
  let t = (s || "").replace(HINT_RE, "");
  t = t.replace(/\s*\bR\s*$/, "").replace(/(解除急停)\s*R$/, "$1");
  return t.trim();
}
export function evText(e: EstopEvLike): string {
  if (e.kind !== "estop" && e.kind !== "watchdog") return e.text ?? "";
  if (e.cause_zh) return e.cause_zh;
  return stripLegacy(e.message_zh || e.text || "");
}
// 标签颜色：锁存中的急停 / 看门狗用 --crit；历史（已解除）一律中性
export function evColor(kind: string, base: string, latched: boolean): string {
  if ((kind === "estop" || kind === "watchdog") && !latched) return "--muted";
  return base;
}
// 告警条（锁存中）的操作提示：只读 fix_hint_zh；没有就不显示
export const bannerHint = (latched: boolean, e?: EstopEvLike | null) => latched && e?.fix_hint_zh ? e.fix_hint_zh.replace(/\s*R\s*$/, "").trim() : "";
const hhmmss = (ms: number) => new Date(ms).toLocaleTimeString("zh-CN", { hour12: false });
import { CLEARED_MSG } from "./r8pre";
export const CLEARED_SP = CLEARED_MSG;
export function clearedLine(tMs: number, prevHead?: string | null): string {
  return `${hhmmss(tMs)} 急停已解除 · ${CLEARED_SP}` + (prevHead ? `（之前：${prevHead}）` : "");
}
// 曲线：锁存 → 解除之间的区间（b=null 表示仍在锁存）
export type Span = { a: number; b: number | null };
export class EstopSpans {
  list: Span[] = [];
  latch(t: number) { const l = this.list[this.list.length - 1]; if (l && l.b == null) return; this.list.push({ a: t, b: null }); if (this.list.length > 20) this.list.shift(); }
  clear(t: number) { const l = this.list[this.list.length - 1]; if (l && l.b == null) l.b = Math.max(t, l.a); }
  marks(): { t: number; tag: string; color: string }[] {
    return this.list.flatMap(s => [{ t: s.a, tag: "急停", color: "--crit" }, ...(s.b != null ? [{ t: s.b, tag: "解除", color: "--muted" }] : [])]);
  }
}
// 恢复急停前目标：值优先取本地服务 latched 事件 / status 里的 sp_before_latch，没有才用界面最后看到/下发的设定值
export class RestoreTarget {
  private lastSent: number | null = null;
  private atLatch: number | null = null;
  shown = false;
  noteSent(v: number) { if (Number.isFinite(v)) this.lastSent = v; }
  onLatch(spBeforeLatch?: number | null) {
    this.atLatch = typeof spBeforeLatch === "number" && Number.isFinite(spBeforeLatch) ? spBeforeLatch : this.lastSent;
    this.shown = false;
  }
  // 锁存期间本地服务补报的值（status 里的 sp_before_latch）覆盖界面兜底值
  onReport(spBeforeLatch?: number | null) { if (typeof spBeforeLatch === "number" && Number.isFinite(spBeforeLatch)) this.atLatch = spBeforeLatch; }
  onClear() { this.shown = this.atLatch != null && this.atLatch !== 0; }
  onEdit() { this.shown = false; }
  value() { return this.shown ? this.atLatch : null; }
  label(unit = "", fmt: (v: number) => string = v => String(+v.toFixed(3))) {
    const v = this.value(); return v == null ? "" : `恢复急停前目标 ${fmt(v)}${unit === "deg" ? "°" : unit ? " " + unit : ""}`;
  }
  // 点击：返回要下发的值并收起按钮（只在点击时调用）
  take(): number | null { const v = this.value(); this.shown = false; return v; }
}
