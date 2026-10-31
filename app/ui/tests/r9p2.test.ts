import assert from "node:assert/strict";
import { IterModel, cardView, verdictLine } from "../src/iterui";
import { toVerdict } from "../src/fieldmap";
const best = { iter: 3, params: { kp: 1.2 }, pass: true, gaps: {} } as any;
const ss = { measured: 0.8, unit: "count", band: { limit: 2, unit: "mm", item: "定位误差", source: "题目 2.3" }, inside: null, note_zh: "" };
// 1) 卡带 inside=null + pass_basis，刷新后 iterate_status 不带 ss_err：从缓存补回，绝不出「达标」
let store: string | null = null;
const a = new IterModel(true); a.cache = { get: () => store, set: v => { store = v; } };
a.onEvent({ type: "iterate.stopped", reason: "pass", best, best_card: 7 }, 0);
a.onEvent({ type: "agent_action", tool: "iterate_apply_best", id: 7, args: { ss_err: ss, pass_basis: "连续 3 轮达标", verdict: "pass", verdict_zh: "已达标" } }, 0);
const b = new IterModel(true); b.cache = a.cache;
b.onStatus({ running: false, result: { type: "iterate.stopped", reason: "pass", best, best_card: 7 } }, 0);
const v = cardView((b.s as any).result);
const all = [v.title, v.reason, v.verdict.text, ...v.gaps].join("\n");
assert.ok(!/达标（|各项指标均已达标|^已达标/m.test(v.verdict.text.replace("（连续 3 轮达标）", "")), all);
assert.equal(v.verdict.v, "unknown"); assert.match(v.verdict.text, /^未判定（连续 3 轮达标）$/);
assert.match(all, /实测 0\.8 count .*≤ 2 mm · 单位不一致，需先标定/);
assert.ok(!all.includes("各项指标均已达标"));
// 2) 后端 iterate_status 直接带卡结果
const c = new IterModel(true);
c.onStatus({ running: false, result: { type: "iterate.stopped", reason: "pass", best, best_card: 9, card: { args: { ss_err: { ...ss, unit: "mm", inside: true }, verdict: "pass", verdict_zh: "已达标（误差 0.8 mm ≤ 2 mm）", pass_basis: "题目 2.3" } } } }, 0);
assert.equal(cardView((c.s as any).result).verdict.text, "已达标（误差 0.8 mm ≤ 2 mm）（题目 2.3）");
// 3) 没有 verdict → 中性「未判定」，即使 pass=true
assert.deepEqual(verdictLine(undefined, null, ""), { v: "unknown", text: "未判定" });
assert.equal(toVerdict({}).zh, "未判定"); assert.equal(toVerdict({ verdict: "fail", verdict_zh: "超出误差带" }).v, "fail");
assert.ok(!all.includes("已连续达标"));
console.log("r9p2 ok");
