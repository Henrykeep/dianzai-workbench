// r8 预检修复 1–6
import { clearedEvent, CLEARED_EV_TEXT, CLEAR_WHERE, CLEARED_MSG, CLEARED_ACT, STALE_V, StaleReads, portsWithSession, latchCauseText, latchHead } from "../src/r8pre.ts";
import { resolveFix, infer } from "../src/progress.ts";
import { blockedCard } from "../src/receipt.ts";
import { CLEARED_TEXT, RETUNE } from "../src/estopbtn.ts";
import { clearedLine } from "../src/estophist.ts";
import { kindOf, mergeEv } from "../src/timeline.ts";
import { evText, evColor } from "../src/estophist.ts";
const ok = (c: boolean, m: string) => { if (!c) throw m; };
// 1 时间线追加中性「急停已解除」，排在最后
const have = [{ i: 1, kind: "connect", text: "连接", log_t: 0, plot_t: 0 }, { i: 7, kind: "estop", text: "急停，板子已锁存", log_t: 1, plot_t: 1 }];
const ce = clearedEvent(have, null, 5);
ok(ce.kind === "estop_clear" && ce.text === CLEARED_EV_TEXT && CLEARED_EV_TEXT === "急停已解除", "事件");
const m = mergeEv(have as any, [ce]); ok(m[m.length - 1] === ce, "最新一条是已解除");
ok(kindOf("estop_clear")[1] === "--muted" && evColor("estop_clear", "--muted", false) === "--muted" && evText(ce) === "急停已解除", "灰色中性");
// 2 解除急停只在红条与顶栏：其它地方 resolveFix 不给按钮，只留文字
ok(resolveFix("estop_clear", () => true) === null, "estop_clear 不出按钮");
ok(blockedCard({ msg_id: "x", state: "blocked", reason: "estop" } as any, () => true).other === null, "Agent 卡无解除按钮");
const b = infer({ current: "调参", connected: true, estop: true, gainsZero: false, paramsDirty: false, selftestFail: false, visited: new Set() } as any).blockers.find((x: any) => x.code === "estop")!;
ok(b.message.includes(CLEAR_WHERE), "页头/导航文字指向红条与顶栏");
ok(resolveFix("connect", () => true)?.kind === "run", "其它动作不受影响");
// 3 灰条与解除提示同一句、一个动作
ok(CLEARED_MSG === "设定值已清零，重新开始实验即可" && CLEARED_TEXT === CLEARED_MSG && clearedLine(0).includes(CLEARED_MSG), "同一句");
ok(RETUNE === CLEARED_ACT && !/需重新开始调参/.test(clearedLine(0) + CLEARED_TEXT), "不再有「需重新开始调参」");
// 4 解除后大字「—（需重新实验）」，新 t0 到达后恢复
ok(STALE_V === "—（需重新实验）", "文案");
const s = new StaleReads(); ok(!s.stale(3), "未解除不 stale");
s.clear(3); ok(s.stale(3) && s.stale(3), "解除后同一 t0 = 旧数据");
ok(!s.stale(9) && !s.stale(3), "新实验后恢复正常");
s.clear(null); ok(s.stale(null), "t0 为空也 stale");
// 5 复用会话：下拉框 = 实际端口
const ports = [{ port: "sim:car_2wd", desc: "仿真 car_2wd", kind: "sim", likely: false }, { port: "sim:motor_pos", desc: "仿真 motor_pos", kind: "sim", likely: false }];
ok(portsWithSession(ports, { connected: true, port: "sim:motor_pos" }).value === "sim:motor_pos", "已在列表");
const r = portsWithSession(ports, { connected: true, port: "/dev/ttyUSB3" }); ok(r.value === "/dev/ttyUSB3" && r.ports[0].port === "/dev/ttyUSB3", "不在列表补上");
ok(portsWithSession(ports, { connected: false, port: "sim:motor_pos" }).value === null, "未连接不改");
// 6 连上即锁存：横幅写原因
for (const c of [null, undefined, {}, { cause_zh: null }, { cause_zh: "null", message_zh: "" }]) ok(latchCauseText(c as any) === "原因未知（重连后未上报）", "null cause " + JSON.stringify(c));
ok(latchCauseText({ cause_zh: "界面急停按钮" }) === "界面急停按钮" && latchCauseText({ message_zh: "心跳丢失 R" }) === "心跳丢失", "有原因");
ok(latchHead(null) === "急停已锁存：原因未知（重连后未上报）", "head");
console.log("✓ r8pre");
