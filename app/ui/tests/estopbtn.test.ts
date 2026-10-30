import { fireEstop, handleEstopMsg, latchedCause, clearedOnce, CLEARED_NOTICE, onEstopEvent, ESTOP_LABEL, traces, latchCleared, onCleared, CLEARED_TEXT, RETUNE } from "../src/estopbtn.ts";
import { Link } from "../src/ws.ts";
// 假 WS：记录 send 时刻
const sent: { t: number; m: any }[] = [];
const fake: any = Object.create(Link.prototype);
Object.assign(fake, { open: true, rid: 0, wait: new Map(), ws: { send: (s: string) => sent.push({ t: performance.now(), m: JSON.parse(s) }) } });
fake.ready = () => new Promise(() => {});   // 让 rpc 永远挂着，模拟 Agent 长调用
// Agent 长调用进行中（agent_ask 未返回 + 主线程正忙）
void fake.rpc("agent_ask", { text: "把参数调好", msg_id: "m1" });
const t0 = performance.now();
const tr = fireEstop(fake, "急停按钮");
const est = sent.find(x => x.m.op === "estop");
if (!est) throw "急停没发出";
const dt = est.t - t0;
if (dt > 10) throw `点击到发出 ${dt} ms > 10 ms`;
if (tr.send! - tr.click > 10) throw "打点超 10 ms";
// 状态文案
if (ESTOP_LABEL.pending !== "正在急停" || ESTOP_LABEL.requested !== "已发送急停") throw "文案";
if (onEstopEvent("requested") !== "requested" || traces.at(-1)!.requested == null) throw "requested 打点";
if (onEstopEvent("latched") !== "latched" || traces.at(-1)!.latched == null) throw "latched 打点";
if (onEstopEvent("bogus") !== null) throw "坏 state";
// 解除：cleared / tx_locked true→false 后只提示，不自动发任何运动或调参请求
if (onEstopEvent("cleared") !== "idle") throw "cleared → idle";
if (!latchCleared(true, false) || latchCleared(false, false) || latchCleared(true, true)) throw "解除判定";
const before = sent.length; let tuned = 0, shown: any = null;
onCleared((text, btn, go) => { shown = { text, btn, go }; }, () => { tuned++; });
const MOTION = /^(cmd|params|set_param|tune|agent_tune|step|run|sweep|params_restore|agent_ask)/;
if (sent.slice(before).some(x => MOTION.test(x.m.op) || x.m.op !== "estop")) throw "解除后自动发了请求 " + JSON.stringify(sent.slice(before));
if (sent.length !== before || tuned) throw "解除后不得自动发任何请求";
if (shown.text !== "已解除，电机保持静止，需重新开始调参" || CLEARED_TEXT !== shown.text || shown.btn.label !== "重新调参") throw "解除提示";
shown.go(); if (tuned !== 1) throw "人点「重新调参」才发起";
if (RETUNE.action !== "tune_relay") throw "重新调参入口";
console.log(`estopbtn ok click→send ${dt.toFixed(3)} ms`);
// 事件处理：状态只看 state；不带 state 的旧 {sent:true} 不改状态
{
  const log: string[] = []; const ui = { setPhase: (p: string) => log.push("p:" + p), showCleared: () => log.push("cleared"), toast: (_t: string, k: string) => log.push("t:" + k) };
  handleEstopMsg({ type: "estop", sent: true, message: "旧回包" } as any, ui as any);
  if (log.length) throw "旧 {sent:true} 不得改状态/弹提示 " + log;
  handleEstopMsg({ type: "estop", state: "requested", sent: true } as any, ui as any);
  handleEstopMsg({ type: "estop", state: "latched" } as any, ui as any);
  if (log.join() !== "p:requested,p:latched") throw "requested/latched " + log;
  log.length = 0; const n0 = sent.length;
  handleEstopMsg({ type: "estop", state: "cleared" } as any, ui as any);
  if (log.join() !== "p:idle,cleared" || sent.length !== n0) throw "cleared 只提示，不发请求 " + log;
  log.length = 0;
  handleEstopMsg({ type: "estop", sent: false, nolink: true, message: "没连板子" } as any, ui as any);
  if (log.join() !== "t:crit,p:idle") throw "未送达要告警 " + log;
  log.length = 0;
  handleEstopMsg({ type: "estop", state: "requested", sent: false } as any, ui as any);
  if (!log.includes("t:crit")) throw "写串口失败要告警";
  handleEstopMsg({ type: "estop", state: "latched", source: "firmware:stall", cause: "stall", message_zh: "左轮堵转" } as any, ui as any);
  if (latchedCause()?.cause !== "stall" || latchedCause()?.message_zh !== "左轮堵转") throw "latched 载荷里的原因";
  handleEstopMsg({ type: "estop", state: "cleared" } as any, ui as any);
  if (latchedCause() !== null) throw "cleared 后清原因";
  // 解除提示只出现一次：cleared 事件 + tx_locked 回落 + agent_notice(estop_cleared) 三路同时到
  let cards = 0; const once = clearedOnce(() => cards++);
  handleEstopMsg({ type: "estop", state: "cleared" } as any, { ...ui, showCleared: () => once.fire() } as any);
  if (latchCleared(true, false)) once.fire();
  if ({ blocker_code: CLEARED_NOTICE }.blocker_code === "estop_cleared") once.fire();
  if (cards !== 1) throw "解除卡出现 " + cards + " 次";
  once.reset(); once.fire(); if (cards !== 2) throw "再次锁存后应能重新提示";
  console.log("estop handler ok");
}
