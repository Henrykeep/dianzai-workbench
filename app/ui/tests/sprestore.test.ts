// 恢复急停前目标：hold 判定 + setpoint_set 一次 + 错误处理（hold 未进 integration，用夹具）
import { holdOf, restoreAllowed, restoreOutcome, restoreClick } from "../src/sprestore.ts";
import { RestoreTarget } from "../src/estophist.ts";
const ok = (c: boolean, m: string) => { if (!c) throw m; };
// 夹具：三处来源
const fx = { status: { hold: { sp_deg: "latched" } }, fields: [{ name: "sp_deg", hold: "timeout" as const }] };
ok(holdOf("sp_deg", fx) === "latched", "status.hold 优先");
ok(holdOf("sp_deg", { fields: [{ name: "sp_deg", hold: "latched" }] }) === "latched", "schema 字段");
ok(holdOf("sp_deg", { params: [{ name: "sp_deg", hold: "timeout" }] }) === "timeout", "参数表");
ok(holdOf("sp_deg", { status: { cmd_timeout_ms: 0 } }) === undefined, "不看 cmd_timeout_ms");
ok(restoreAllowed("latched") && !restoreAllowed("timeout") && !restoreAllowed(undefined) && !restoreAllowed(null), "只有 latched 出按钮");
// 结果
const s = restoreOutcome(null); ok(!s.keep && s.note === "", "成功收起");
for (const code of ["estop_locked", "iter_busy", "invalid_param"]) {
  const r = restoreOutcome({ code, message_zh: code + " 说明" }); ok(r.keep && r.note === code + " 说明", code + " 留按钮写 message_zh");
}
const h = restoreOutcome({ code: "hold_timeout", message_zh: "板子已超时归零" }); ok(!h.keep && h.note === "板子已超时归零", "hold_timeout 收起");
ok(restoreOutcome({ code: "iter_busy", message: "fallback" }).note === "fallback", "无 message_zh 用 message");
(async () => {
// 点击：只调一次 setpoint_set，参数 {name, value}；进行中重复点忽略
const calls: any[] = []; let rel!: () => void;
const rpc = (op: string, a: any) => { calls.push([op, a]); return new Promise<void>(r => { rel = r; }); };
const busy = { on: false };
const p1 = restoreClick(rpc, "sp_deg", 90, busy), p2 = restoreClick(rpc, "sp_deg", 90, busy);
rel();
const [r1, r2] = await Promise.all([p1, p2]);
ok(calls.length === 1 && calls[0][0] === "setpoint_set" && calls[0][1].name === "sp_deg" && calls[0][1].value === 90, "只发一次 " + JSON.stringify(calls));
ok(r2 === null && r1!.keep === false, "成功收起");
const r3 = await restoreClick(() => Promise.reject({ code: "estop_locked", message_zh: "急停中" }), "sp_deg", 90, busy);
ok(r3!.keep && r3!.note === "急停中" && !busy.on, "失败留按钮");
// 值：sp_before_latch 优先，兜底界面值
const T = new RestoreTarget(); T.noteSent(45); T.onLatch(90); T.onClear(); ok(T.value() === 90, "sp_before_latch");
const U = new RestoreTarget(); U.noteSent(45); U.onLatch(null); U.onClear(); ok(U.value() === 45, "兜底");
console.log("✓ sprestore");
})().catch(e => { console.error(e); process.exit(1); });
