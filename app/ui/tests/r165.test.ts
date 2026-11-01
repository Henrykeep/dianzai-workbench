// #165 原因码不裸露：板子拒绝 / 标定录制失败 / 导航步提示 / 急停行 / 提交被拒 / 角色卡等一律经 codeZh（plainZh），未知码「其他原因（代码 xxx）」
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setReasonCodes, plainZh, codeZh } from "../src/reasoncodes";
import { validReasons } from "../src/datatables";
import { rejectHint } from "../src/batch1";
import { measureFailZh } from "../src/calwiz";
import { stepHint } from "../src/progress";
import { estopLine } from "../src/estop";
import { declinedHtml } from "../src/commitcard";
import { roleCardHtml } from "../src/roles";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" } as any)[c]);
setReasonCodes(validReasons({ no_result: { zh: "板子没回结果" }, wave_timeout: { zh: "录波超时", message_zh: "录波超时，板子没在时限内回数据" } }));
const U = (c: string) => `其他原因（代码 ${c}）`;
// plainZh：码 → 表；中文原样；数字码也走表；空 → ""
assert.equal(plainZh("no_result"), "板子没回结果"); assert.equal(plainZh("wave_timeout"), "录波超时，板子没在时限内回数据");
assert.equal(plainZh("zz_weird"), U("zz_weird")); assert.equal(plainZh(7), U("7")); assert.equal(plainZh("7"), U("7"));
assert.equal(plainZh("接线松动"), "接线松动"); assert.equal(plainZh(undefined), ""); assert.equal(codeZh("zz"), U("zz"));
// batch1.ts 板子拒绝
assert.equal(rejectHint({ reason: "range", requested: 9 }).startsWith("超出量程"), true);
assert.equal(rejectHint({ reason: "zz_weird" }), `板子拒绝：${U("zz_weird")}`);
assert.equal(rejectHint({ reason: 5, requested: 2, current: 1 }), `板子拒绝：${U("5")}：请求 2，板上仍为 1`);
assert.equal(rejectHint({ reason: "no_result" }), "板子拒绝：板子没回结果");
assert.ok(!/（zz_weird）/.test(rejectHint({ reason: "zz_weird" })));
// calwiz.ts 标定录制失败
assert.equal(measureFailZh("enc", "wave_timeout"), "enc：录波超时，板子没在时限内回数据");
assert.equal(measureFailZh("enc", "zz_weird"), `enc：${U("zz_weird")}`);
assert.equal(measureFailZh("enc", "板子忙"), "enc：板子忙"); assert.equal(measureFailZh("enc", undefined), "enc：未上报原因");
// progress.ts 导航步提示
assert.match(stepHint({ title: "烧录", state: "blocked", reason: "zz_weird" }), /（其他原因（代码 zz_weird））$/);
assert.match(stepHint({ title: "烧录", state: "blocked", reason: "no_result" }), /（板子没回结果）$/);
assert.match(stepHint({ title: "烧录", state: "blocked", detail: "先接线", reason: "zz_weird" }), /：先接线$/);
// estop.ts 急停行（reason_zh 里误给了码）；未知 reason 码本来就落到通用「急停」
assert.match(estopLine({ reason_zh: "zz_weird" }, null).line, /其他原因（代码 zz_weird），已锁存/);
assert.equal(estopLine({ reason: "zz_weird" }, null).line, "急停，已锁存");
// commitcard.ts 提交被拒
assert.match(declinedHtml({ reason: "zz_weird", fix: "" }, esc, null), /未提交：其他原因（代码 zz_weird）/);
assert.match(declinedHtml({ reason: "钩子失败", fix: "" }, esc, null), /未提交：钩子失败/);
// roles.ts 角色卡
const rc = roleCardHtml({ reason: "zz_weird", missing: [], suggested: {} });
assert.match(rc, /其他原因（代码 zz_weird）/); assert.ok(!/>zz_weird</.test(rc));
// agent.ts / main.ts 里的 DOM 拼接：源码里这些原因字段都包了 plainZh
const src = (f: string) => readFileSync(`src/${f}`, "utf8");
for (const [f, pat] of [["agent.ts", "esc(plainZh(m.reason))"], ["agent.ts", "esc(plainZh(v.reason))"], ["agent.ts", "规则建议：${esc(plainZh(r.reason))}"], ["agent.ts", "原因：${esc(plainZh(r.decl!.reason))}"], ["main.ts", "<p>${esc(plainZh(m.reason))}"]] as const)
  assert.ok(src(f).includes(pat), `${f}: ${pat}`);
setReasonCodes(null);
console.log("r165 ok");
