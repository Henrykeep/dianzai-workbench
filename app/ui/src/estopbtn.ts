// 急停按钮（安全 P0）：点击 → 同步 ws.send，不排队、不防抖、不等任何 await（Agent 长调用进行中也一样）。
// 打点：click / send / requested / latched，用 performance.now()，写进调试日志 window.__dzEstop。
export type EstopPhase = "idle" | "pending" | "requested" | "latched";
export const ESTOP_LABEL: Record<EstopPhase, string> = { idle: "急停", pending: "正在急停", requested: "已发送急停", latched: "急停已锁存" };
export type Trace = { src: string; click: number; send?: number; requested?: number; latched?: number };
export const traces: Trace[] = [];
const now = () => performance.now();
export function fireEstop(link: { fire(op: string, a: Record<string, unknown>): void }, src: string): Trace {
  const t: Trace = { src, click: now() };
  link.fire("estop", { src });            // 第一件事就发，其余（界面、日志）都在发出之后
  t.send = now();
  traces.push(t); if (traces.length > 20) traces.shift();
  log(`estop click→send ${(t.send - t.click).toFixed(2)} ms (${src})`);
  return t;
}
// 收到 estop {source, state: requested|latched}：记到最近一次点击上
// 事件格式已定：只用 {type:"estop", seq, state: requested|latched|cleared, source, cause?, message_zh?, t}
export function onEstopEvent(state: string): EstopPhase | null {
  if (state === "cleared") { log("estop cleared"); return "idle"; }
  if (state !== "requested" && state !== "latched") return null;
  const t = traces[traces.length - 1];
  if (t && t[state] == null) { t[state] = now(); log(`estop click→${state} ${(t[state]! - t.click).toFixed(1)} ms`); }
  return state;
}
function log(s: string) {
  try { console.debug("[dz-estop]", s); (globalThis as any).__dzEstop = traces; } catch { /* 调试日志失败不影响急停 */ }
}

// 解除确认（tx_locked true → false）：只提示，不自动发任何运动 / 调参请求；「重新调参」由人点了才发起
export const CLEARED_TEXT = "已解除，电机保持静止，需重新开始调参";
export const RETUNE = { label: "重新调参", action: "tune_relay" } as const;
export function latchCleared(prev: boolean, cur: boolean) { return prev && !cur; }
export function onCleared(show: (text: string, btn: typeof RETUNE, onClick: () => void) => void, startTune: () => void) {
  show(CLEARED_TEXT, RETUNE, () => startTune());   // startTune 只在人点击时调用
}

// WS 上的 type:"estop" 消息：状态只看 state（requested|latched|cleared）。
// 急停操作的回包也带 state:"requested" 与 sent（发送确认）；没有 state 的只可能是“没送达”（未连接 / 回放中）→ 告警，不改状态。
export type EstopMsg = { type: "estop"; state?: string; cause?: string; message_zh?: string; sent?: boolean; message?: string };
export type EstopUi = { setPhase(p: EstopPhase): void; showCleared(): void; toast(text: string, kind: "info" | "crit", ms: number): void };
let cause: { cause: string; message_zh: string } | null = null;
export const latchedCause = () => cause;
export function handleEstopMsg(m: EstopMsg, ui: EstopUi): void {
  if (m.state) {
    if (m.state === "latched" && (m.cause || m.message_zh)) cause = { cause: m.cause || "", message_zh: m.message_zh || "" };   // 急停原因随 latched 载荷到达（不再有 estop_cause 事件）
    if (m.state === "cleared") cause = null;
    const p = onEstopEvent(m.state);
    if (p) ui.setPhase(p);
    if (m.state === "cleared") ui.showCleared();
    if (m.state === "requested" && m.sent === false) ui.toast(m.message || "急停没有送达，请直接断电或拔电池。", "crit", 15000);
    return;
  }
  if (m.sent === false) { ui.toast(m.message || m.message_zh || "急停没有送达任何板子", "crit", 15000); ui.setPhase("idle"); }
  // 不带 state 的 {sent:true}：约定里不存在，忽略（不据此改状态）
}

// 解除后只展示一张卡：cleared 事件、tx_locked true→false、本地服务的 agent_notice(estop_cleared) 三个来源都汇到这里，
// 同一次解除只显示一次；再次锁存时 reset。Agent 面板不再单独渲染 estop_cleared。
export const CLEARED_NOTICE = "estop_cleared";
export function clearedOnce(show: () => void) {
  let shown = false;
  return { fire() { if (shown) return false; shown = true; show(); return true; }, reset() { shown = false; } };
}
