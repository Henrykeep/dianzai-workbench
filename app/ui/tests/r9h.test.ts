import assert from "node:assert";
import { readFileSync, readdirSync } from "node:fs";
import { estopLine } from "../src/estop";
import { toVerdict, DOWNSCALE_ZH, VERDICT_ZH, toMetricsCard } from "../src/fieldmap";
import { metricCardHtml, summary } from "../src/metriccard";
import { verdictLine, cardView, resultCardHtml } from "../src/iterui";
// fix-r9c 72708e8 定稿：旧名不再读
const src = readdirSync("src").filter(f => f.endsWith(".ts")).map(f => readFileSync("src/" + f, "utf8")).join("\n");
for (const old of ["gap_ms", "result.cleared", "iterate.cleared", "result.clear\"", "cause.value", "cause?.value"]) assert.ok(!src.includes(old), "旧名还在：" + old);
assert.equal(estopLine({ reason: "heartbeat_lost", reason_zh: "心跳超时", gap_ms: 1700, cause: { value: 1700 } }, {}).line.includes("1700"), false);
// 手动急停不带 measured/threshold → 不显示这两个槽
assert.equal(estopLine({ reason: "manual", latched_at: new Date(2026, 0, 1, 8, 7).getTime() }, {}).line, "08:07 手动急停，已锁存");
// 心跳：threshold_ms null → 阈值后端未给
assert.equal(estopLine({ reason: "heartbeat_lost", reason_zh: "心跳超时", latched_at: new Date(2026, 0, 1, 8, 7).getTime(), measured_ms: 1601, threshold_ms: null }, {}).line, "08:07 心跳超时 1601 ms，已锁存");
// #129 降幅测试：verdict partial / amp_reduced → 绝不显示通过，warning_zh 原文琥珀色警告
const dv = toVerdict({ verdict: "partial", verdict_zh: "未验题面幅度", amp_reduced: true, warning_zh: "按 50% 幅度测试，未验题面幅度" });
assert.equal(dv.v, "unknown"); assert.equal(dv.warn, "按 50% 幅度测试，未验题面幅度");
assert.deepEqual(verdictLine(dv, null, ""), { v: "warn", text: "按 50% 幅度测试，未验题面幅度" });
assert.equal(toVerdict({ verdict: "partial" }).warn, DOWNSCALE_ZH); assert.equal(VERDICT_ZH.partial, "未验题面幅度");
assert.equal(toVerdict({ verdict: "pass", amp_reduced: true }).v, "unknown");
assert.equal(toVerdict({ verdict: "fail", amp_reduced: true }).v, "fail");
assert.equal(toVerdict({ verdict: "pass" }).warn, undefined);
const r: any = { reason: "pass", verdict: dv, best: { iter: 2, params: { kp: 1 } } };
assert.equal(cardView(r).verdict.v, "warn");
const h = resultCardHtml(r, s => s, { canApply: true, applyReady: true }); assert.ok(h.includes("按 50% 幅度测试，未验题面幅度") && !h.includes("通过"));
// 指标卡逐项
const mk = (x: any) => ({ metrics_card: { task_kind: "control", items: [{ name: "m1", verdict: "pass", target: { cmp: "<=", threshold: 5, unit: "%" }, measured: { value: 3, unit: "%" }, ...x }] } });
const c1 = toMetricsCard(mk({ verdict: "partial", verdict_zh: "未验题面幅度", amp_reduced: true, amp_spec: 100, amp_tested: { value: 50, unit: "mm" }, warning_zh: "只测了一半幅度" }))!;
assert.equal(c1.items[0].verdict, "partial"); assert.deepEqual(c1.items[0].amp, { reduced: true, spec: "100", tested: "50 mm" });   // #140 不从指标单位猜幅度单位
assert.equal(toMetricsCard(mk({ amp_reduced: true }))!.items[0].verdict, "partial");   // 后端 pass + amp_reduced 也不算达标
assert.equal(toMetricsCard(mk({}))!.items[0].amp, null);
const mh = metricCardHtml(mk({ verdict: "partial", amp_reduced: true, amp_spec: { value: 2, unit: "V" }, amp_tested: { value: 1, unit: "V" }, warning_zh: "只测了一半幅度" }));
assert.ok(mh.includes("题面幅度 2 V，实测幅度 1 V") && mh.includes('class="mc-warn partial">只测了一半幅度') && mh.includes("mc-it partial") && !mh.includes(">达标<"));
assert.ok(summary(c1).text.includes("未验题面幅度 1") && summary(c1).pass === 0);
assert.equal(toMetricsCard(mk({ amp_reduced: false, amp_spec: 1, amp_tested: null }))!.items[0].amp!.tested, "后端未给");
console.log("✓ r9h：旧名不读 / 手动急停无间隔槽 / 阈值后端未给 / 降幅测试不当通过");
