import { fireEstop, onEstopEvent, ESTOP_LABEL, traces } from "../src/estopbtn.ts";
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
console.log(`estopbtn ok click→send ${dt.toFixed(3)} ms`);
