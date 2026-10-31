import { humanize } from "../src/errors.ts";
import { estopView, latchedOf, watchdogText, SOURCE_TEXT, UNREPORTED } from "../src/estop.ts";
import { infer } from "../src/progress.ts";
const h = humanize("HTTP 403 error code: 1010");
if (!h || !h.what.includes("拒绝") || !h.raw.includes("1010")) throw "403 翻译";
if (humanize("一切正常") !== null) throw "无匹配不翻译";
// #25 急停来源：三种固定文案；firmware 优先 message_zh；都没有 → 未上报 + 最近心跳时间；不再有「来源未知」
for (const s of ["heartbeat_lost", "ui", "selftest"]) if (estopView({ kind: "estop", source: s }, { message_zh: "不该用这个" }).head !== SOURCE_TEXT[s]) throw "固定文案 " + s;
if (estopView({ source: "firmware:stall" }, { cause: "stall", message_zh: "左轮堵转 0.5 s，已停车" }).head !== "左轮堵转 0.5 s，已停车") throw "firmware 用 message_zh";
if (!estopView({ source: "firmware:stall" }, null).head.includes("stall")) throw "firmware 无说明时写原因码";
if (estopView({ kind: "estop" }, { message_zh: "电池欠压" }).head !== "电池欠压") throw "无 source 有 message_zh";
const un = estopView({ kind: "estop" }, null, Date.UTC(2026, 9, 30, 19, 5, 7));
if (un.head !== UNREPORTED || !/最近一次心跳 \d\d:05:07/.test(un.detail)) throw "未上报 + 心跳时间 " + un.detail;
if (estopView({ kind: "estop" }, null, null).detail !== "最近一次心跳：未收到") throw "从没收到心跳";
if (JSON.stringify([estopView({}, null), SOURCE_TEXT]).includes("来源未知")) throw "去掉来源未知";
if (!watchdogText({ text: "2.0 s 没收到板子心跳" }).startsWith("心跳超时：")) throw "心跳超时单列";
// #20 锁存 → 本地服务断开 → 重连：只认本地服务上报，前端不自行重置
let L = latchedOf({ tx_locked: true }, false, true); if (!L) throw "锁存";
L = latchedOf({}, L, false); if (!L) throw "断开期间保持锁定";
L = latchedOf({ connected: false } as any, L, true); if (!L) throw "重连后 status 未带 tx_locked → 保持";
L = latchedOf({ tx_locked: true }, L, true); if (!L) throw "重连后本地服务仍报锁存";
if (latchedOf({ tx_locked: false }, true, true)) throw "只有本地服务报解除才解除";
const p = infer({ current: "项目", connected: false, estop: false, gainsZero: false, paramsDirty: true, selftestFail: false, visited: new Set(["项目"]) });
if (p.steps.length !== 7 || p.steps[0].id !== "req" || p.current !== "req") throw "7 步旅程";
if (!p.blockers.some(b => b.code === "no_board" && b.fix_action === "connect")) throw "no_board blocker";
if (!p.blockers.some(b => b.code === "params_not_saved")) throw "params blocker";
console.log("r4 ok");
