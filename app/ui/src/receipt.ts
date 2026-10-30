// 消息回执（问题池 #25）：发消息带 msg_id → 立即「已发送」；本地服务回 agent_ack {msg_id, state}
// queued →「已送达」，running →「处理中」，blocked（reason: estop）→ 提示卡「已急停，请先解除」；3 s 无 ack →「未送达」+「重发」。
// 收到这条消息的回答也算已送达（兼容还没推 ack 的本地服务）。
import type { Card } from "./agentwatch";
import { resolveFix } from "./progress";
export type AckState = "queued" | "running" | "blocked";
export type Ack = { msg_id: string; state: AckState; reason?: string; message?: string; fix_action?: string };
export type RState = "sent" | AckState | "lost" | "done";
export const RECEIPT_LABEL: Record<RState, string> = { sent: "已发送", queued: "已送达", running: "处理中", blocked: "已急停", lost: "未送达", done: "" };
export const ACK_TIMEOUT_MS = 3000;
let seq = 0;
export const newMsgId = () => `m${Date.now().toString(36)}-${(seq++).toString(36)}`;
type Timer = ReturnType<typeof setTimeout>;
export class Receipts {
  private m = new Map<string, { state: RState; timer?: Timer }>();
  constructor(private on: (id: string, s: RState, ack?: Ack) => void,
    // 包一层：浏览器里把 setTimeout 当方法调用会报 Illegal invocation
    private setT: (f: () => void, ms: number) => Timer = (f, ms) => setTimeout(f, ms), private clrT: (t: Timer) => void = t => clearTimeout(t)) {}
  state(id: string) { return this.m.get(id)?.state; }
  private set(id: string, s: RState, ack?: Ack) {
    const e = this.m.get(id); if (!e) return;
    if (s !== "sent" && e.timer) { this.clrT(e.timer); e.timer = undefined; }
    e.state = s; this.on(id, s, ack);
  }
  sent(id: string) {
    this.m.set(id, { state: "sent" });
    this.m.get(id)!.timer = this.setT(() => { if (this.m.get(id)?.state === "sent") this.set(id, "lost"); }, ACK_TIMEOUT_MS);
    this.on(id, "sent");
  }
  // 迟到的 ack 也认：本地服务确实收到了，撤掉「未送达」
  ack(a: Ack): boolean {
    if (!a?.msg_id || !this.m.has(a.msg_id) || !["queued", "running", "blocked"].includes(a.state)) return false;
    if (this.m.get(a.msg_id)!.state === "done") return false;
    this.set(a.msg_id, a.state, a); return true;
  }
  replied(id: string) { if (this.m.has(id)) this.set(id, "done"); }
  failed(id: string) { if (this.m.has(id)) this.set(id, "lost"); }
}
// blocked 提示卡：标题固定，正文 = 本地服务给的 message，按钮走统一 fix_action（estop_clear →「解除并继续」）
export function blockedCard(a: Ack, has?: (ui: string) => boolean): Card {
  const fa = a.fix_action || (a.reason === "estop" ? "estop_clear" : "");
  return {
    title: a.reason === "estop" || fa === "estop_clear" ? "已急停，请先解除" : "消息暂不能执行",
    why: a.message || "本地服务暂停了这条消息",
    fix: fa === "estop_clear" ? "确认现场安全后点「解除并继续」，本地服务会接着执行这条消息" : "按按钮处理后，本地服务会接着执行",
    detail: `msg_id: ${a.msg_id} · state: ${a.state}${a.reason ? " · reason: " + a.reason : ""}`,
    retry: false, other: fa ? resolveFix(fa, has) : null, otherId: fa || undefined,
  };
}
// progress.changed 带来新 blocker：只对新出现的 code 发一条 Agent 消息（按钮走统一 fix_action）
export function newBlockers<T extends { code: string }>(prev: Set<string>, cur: T[]): T[] {
  const out = cur.filter(b => !prev.has(b.code));
  prev.clear(); cur.forEach(b => prev.add(b.code));
  return out;
}
// agent_notice {blocker_code, what, source, suggestion, fix_action, human_only}：一条 Agent 消息，先结论，再「发生了什么 · 原因来自 · 建议」
export type Notice = { blocker_code: string; what: string; source?: string; suggestion?: string; fix_action?: string | null; human_only?: boolean };
export function noticeView(n: Notice) {
  return {
    head: n.human_only ? "结论：需要人工确认后才能继续" : "结论：处理后即可继续",
    lines: [`发生了什么：${n.what}`, `原因来自：${n.source || "本地服务未上报"}`, `建议：${n.suggestion || "按下方按钮处理"}`],
    tag: n.human_only ? "需人工确认" : "",
  };
}
// 同一 blocker_code 未清除前只显示一次；progress 里不再有该 code 即视为清除
export class NoticeGate {
  shown = new Set<string>();
  offer(code: string) { if (!code || this.shown.has(code)) return false; this.shown.add(code); return true; }
  sync(codes: string[]) { for (const c of [...this.shown]) if (!codes.includes(c)) this.shown.delete(c); }
}
