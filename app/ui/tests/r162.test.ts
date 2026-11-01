// #162 卡片上的原因码 / 可能原因码：查打包原因表到 message_zh（没有就 zh）；不认识的码显示「其他原因（代码 xxx）」，绝不露裸英文码
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setReasonCodes, reasonZh, codeZh, stopCauses, otherReasonZh } from "../src/reasoncodes";
import { validReasons } from "../src/datatables";
import { stopReasonZh, resultCardHtml } from "../src/iterui";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" } as any)[c]);
const real = JSON.parse(readFileSync("../../docs/dev/reason_codes.json", "utf8"));
setReasonCodes(real);
// 打包表里的每个码：卡片原因 = message_zh || zh
for (const [k, v] of Object.entries<any>(real)) assert.equal(codeZh(k), v.message_zh || v.zh, k);
// 不认识的码（含 zz_unlisted_code，表里没有的码；noise_amplified_saturation 已在 generic-tuning 的表里）
assert.equal(otherReasonZh("x"), "其他原因（代码 x）");
assert.equal(reasonZh("zz_unlisted_code", {}), "其他原因（代码 zz_unlisted_code）");
assert.equal(stopReasonZh({ reason: "zz_unlisted_code" } as any, []), "其他原因（代码 zz_unlisted_code）");
const sc = stopCauses({ reason: "no_improve", causes: ["zz_unlisted_code", { code: "zz_weird" }, "供电不足", { code: "no_improve" }] });
assert.deepEqual(sc.causes, ["其他原因（代码 zz_unlisted_code）", "其他原因（代码 zz_weird）", "供电不足", real.no_improve.message_zh || real.no_improve.zh]);
const card = resultCardHtml({ reason: "zz_unlisted_code", causes: ["zz_unlisted_code", "zz_weird"], best: null } as any, esc, { canApply: true, applyReady: true });
assert.match(card, /其他原因（代码 zz_unlisted_code）/);
assert.ok(!/>(zz_unlisted_code|zz_weird)</.test(card), "卡片里不能有裸英文码");
assert.ok(!/<li>[a-z_]+<\/li>/.test(card));
// 表里有 message_zh 时优先 message_zh
setReasonCodes(validReasons({ ...real, noise_amplified_saturation: { zh: "噪声放大饱和", kind: "tune", message_zh: "微分过大放大了噪声，执行器长时间饱和" } }));
assert.equal(codeZh("noise_amplified_saturation"), "微分过大放大了噪声，执行器长时间饱和");
assert.deepEqual(stopCauses({ causes: ["noise_amplified_saturation"] }).causes, ["微分过大放大了噪声，执行器长时间饱和"]);
assert.equal(codeZh("no_msg", { no_msg: "兜底" }), "兜底");
// 中文串原样，不当成码
assert.deepEqual(stopCauses({ causes: ["接线松动"] }).causes, ["接线松动"]);
setReasonCodes(null);
console.log("r162 ok");
