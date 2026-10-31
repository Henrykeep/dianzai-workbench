import assert from "node:assert";
import { readFileSync, readdirSync } from "node:fs";
import { estopLine } from "../src/estop";
import { toVerdict, DOWNSCALE_ZH } from "../src/fieldmap";
import { verdictLine, cardView, resultCardHtml } from "../src/iterui";
// fix-r9c 72708e8 定稿：旧名不再读
const src = readdirSync("src").filter(f => f.endsWith(".ts")).map(f => readFileSync("src/" + f, "utf8")).join("\n");
for (const old of ["gap_ms", "result.cleared", "iterate.cleared", "result.clear\"", "cause.value", "cause?.value"]) assert.ok(!src.includes(old), "旧名还在：" + old);
assert.equal(estopLine({ reason: "heartbeat_lost", reason_zh: "心跳超时", gap_ms: 1700, cause: { value: 1700 } }, {}).line.includes("1700"), false);
// 手动急停不带 measured/threshold → 不显示这两个槽
assert.equal(estopLine({ reason: "manual", latched_at: new Date(2026, 0, 1, 8, 7).getTime() }, {}).line, "08:07 手动急停，已锁存");
// 心跳：threshold_ms null → 阈值后端未给
assert.equal(estopLine({ reason: "heartbeat_lost", reason_zh: "心跳超时", latched_at: new Date(2026, 0, 1, 8, 7).getTime(), measured_ms: 1601, threshold_ms: null }, {}).line, "08:07 心跳超时 1601 ms（阈值后端未给），已锁存");
// 降幅测试：绝不显示通过，原文警告
const dv = toVerdict({ verdict: "pass", verdict_zh: "通过", step_reduced: true, downscale_zh: "按降幅测试，未验题面幅度（幅度 50%）" });
assert.equal(dv.v, "unknown"); assert.equal(dv.warn, "按降幅测试，未验题面幅度（幅度 50%）");
assert.deepEqual(verdictLine(dv, null, ""), { v: "warn", text: "按降幅测试，未验题面幅度（幅度 50%）" });
assert.equal(toVerdict({ verdict: "pass", step_reduced: true }).warn, DOWNSCALE_ZH);
assert.equal(toVerdict({ verdict: "pass", verdict_zh: DOWNSCALE_ZH }).v, "unknown");
assert.equal(toVerdict({ verdict: "fail", downscaled: true }).v, "fail");
assert.equal(toVerdict({ verdict: "pass" }).warn, undefined);
const r: any = { reason: "pass", verdict: dv, best: { iter: 2, params: { kp: 1 } } };
assert.equal(cardView(r).verdict.v, "warn");
const h = resultCardHtml(r, s => s, { canApply: true, applyReady: true }); assert.ok(h.includes("按降幅测试，未验题面幅度（幅度 50%）") && !h.includes(">通过<"));
console.log("✓ r9h：旧名不读 / 手动急停无间隔槽 / 阈值后端未给 / 降幅测试不当通过");
