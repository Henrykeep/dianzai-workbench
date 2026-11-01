// #163 整定结果卡：improvement_info.causes 单独一块；improvement:null → 初值已达标，未调参（中性，只有「保留初值」）；default_action 定主按钮；
// 只有 improvement === "confirmed" 时「采用」才可能是主按钮
import assert from "node:assert/strict";
import { improvementOf, improvementConfirmed } from "../src/fieldmap";
import { resultCardHtml } from "../src/iterui";
import { setReasonCodes } from "../src/reasoncodes";
setReasonCodes(null);
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" } as any)[c]);
const best = { iter: 2, params: { kp: 4 } };
const card = (r: any) => resultCardHtml({ best, ...r } as any, esc, { canApply: true, applyReady: true });
const primaryAdopt = (h: string) => /<wa-button variant="brand"[^>]*id="it-write"/.test(h);
const adopt = (h: string) => /id="it-write"/.test(h);
// improvement_info 优先；causes 只取 improvement_info.causes，顶层 causes 仍是未达标诊断
const ii = { improvement: "inconclusive", reason: "improvement_unconfirmed", message_zh: "噪声大无法确认", causes: ["测量噪声大", "采样窗口偏短"], default_action: "keep_initial" };
const g = improvementOf({ improvement: "inconclusive", causes: ["供电不足"], improvement_info: ii })!;
assert.deepEqual(g.causes, ["测量噪声大", "采样窗口偏短"]); assert.equal(g.msg, "噪声大无法确认"); assert.equal(g.def, "keep_initial");
const h = card({ reason: "improvement_unconfirmed", improvement: "inconclusive", improvement_info: ii, causes: ["供电不足"] });
assert.match(h, /id="rc-icauses"[^]*测量噪声大[^]*采样窗口偏短/); assert.match(h, /id="rc-causes"[^]*供电不足/);
assert.ok(!/id="rc-icauses"[^]*供电不足[^]*<\/div>[^]*id="rc-causes"/.test(h), "两块分开");
assert.match(h, /<wa-button variant="brand"[^>]*id="it-default"[^>]*keep_initial[^>]*>保留初值/);
assert.ok(adopt(h) && !primaryAdopt(h), "inconclusive：采用是次要按钮");
// 没有 default_action 的 inconclusive 也不让采用当主按钮
assert.ok(!primaryAdopt(card({ improvement: "inconclusive", reason: "improvement_unconfirmed" })));
// improvement:null
const un = { improvement: null, reason: null, message_zh: "初值已满足题面，本次没有改动参数", causes: [], default_action: "keep_initial" };
const n = improvementOf({ improvement: null, improvement_info: un })!;
assert.equal(n.head, "初值已达标，未调参"); assert.equal(n.adopt, "none"); assert.equal(n.tone, "neutral");
assert.equal(improvementOf({ improvement: null })!.msg, "初值已达标，未调参");
assert.equal(improvementOf({ improvement: null })!.def, "keep_initial", "null 没给 default_action 也只有保留初值");
for (const r of [{ reason: "pass", improvement: null, default_action: "keep_initial", improvement_info: un }, { reason: "pass", improvement: null }]) {
  const nh = card(r);
  assert.match(nh, /初值已达标，未调参/); assert.ok(!adopt(nh), "null：没有采用");
  assert.match(nh, /id="it-default"[^>]*keep_initial[^>]*>保留初值/); assert.match(nh, /it-verdict neutral/); assert.ok(!/id="rc-icauses"/.test(nh));
}
// worse：没有采用
assert.ok(!adopt(card({ improvement: "worse", reason: "kept_initial", default_action: "keep_initial" })));
// 采用只有 confirmed 才是主按钮
assert.ok(improvementConfirmed({ improvement: "confirmed" })); assert.ok(improvementConfirmed({ improvement_info: { improvement: "confirmed" } }));
assert.ok(!improvementConfirmed({})); assert.ok(!improvementConfirmed({ improvement: "maybe" }));
assert.ok(primaryAdopt(card({ reason: "pass", improvement: "confirmed" })), "confirmed：采用是主按钮");
assert.ok(primaryAdopt(card({ reason: "pass", improvement_info: { improvement: "confirmed", default_action: "adopt" } })));
for (const r of [{ reason: "pass" }, { reason: "pass", improvement: "maybe_new_kind" }]) { const x = card(r); assert.ok(adopt(x) && !primaryAdopt(x), JSON.stringify(r)); }
console.log("r163 ok");
