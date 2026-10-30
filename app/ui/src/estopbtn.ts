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
