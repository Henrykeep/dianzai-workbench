import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { actGateOf, gateBannerHtml, gateReconnect } from "../src/actgate";
import { RESUME_TO_F, isResumeTimeout } from "../src/fieldmap";
import { setReasonCodes } from "../src/reasoncodes";
const esc = (s: string) => String(s).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);
// 恢复连接超时：文案取 message_zh，其次原因表；带「重新连接」；执行器锁（actGateOf 非空）
const code = RESUME_TO_F.codes[0];
const g = actGateOf({ link: { type: "link.state", board: "lost", reason: code, message_zh: "恢复连接超时（测试文案甲）" } })!;
assert.ok(g && g.reconnect); assert.equal(g.text, "恢复连接超时（测试文案甲）");
const h = gateBannerHtml(g, esc); assert.match(h, /测试文案甲/); assert.match(h, /data-gate-reconnect/); assert.match(h, new RegExp(RESUME_TO_F.btnZh));
setReasonCodes({ [code]: { zh: "表里的超时文案乙", kind: "blocker" } });
assert.equal(actGateOf({ link: { board: "lost", reason: code } })!.text, "表里的超时文案乙", "没 message_zh 用原因表");
// fix_action 是重连类也认（码名未定时）
assert.ok(isResumeTimeout({ reason: "something_new", fix_action: "reconnect" }));
assert.ok(actGateOf({ link: { reason: "something_new", fix_action: "reconnect", message_zh: "丙" } })!.reconnect);
// 普通 resuming 仍是原闸门、无按钮；已连接无闸门
const r = actGateOf({ link: { reason: "resuming" } })!; assert.equal(r.code, "resuming"); assert.ok(!r.reconnect); assert.ok(!/data-gate-reconnect/.test(gateBannerHtml(r, esc)));
assert.equal(actGateOf({ link: { board: "connected", reason: null } }), null);
// 动作：后端定义 op 就发 op，否则 ws 重拨
const calls: string[] = []; const L = { fire: (op: string) => calls.push("op:" + op), reconnect: () => calls.push("ws") };
gateReconnect(L); assert.deepEqual(calls, ["ws"]);
(RESUME_TO_F as any).op = "rehello"; gateReconnect(L); assert.deepEqual(calls, ["ws", "op:rehello"]); (RESUME_TO_F as any).op = null;
// 不写死文案：actgate / main 里没有超时中文
const src = readFileSync("src/actgate.ts", "utf8") + readFileSync("src/main.ts", "utf8");
assert.ok(!/超时/.test(src.replace(/\/\/.*$/gm, "")), "不写死超时文案");
assert.match(readFileSync("src/main.ts", "utf8"), /data-gate-reconnect[^\n]*gateReconnect\(link\)/);
assert.match(readFileSync("src/ws.ts", "utf8"), /reconnect\(\)/);
console.log("r160 ok");
