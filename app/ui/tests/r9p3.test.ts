import assert from "node:assert/strict";
import { lockWritesIn, WRITE_SEL, enumZh, sourceZh, simStartText } from "../src/batch1";
import { sourceLabel, toCompare } from "../src/fieldmap";
import { IterModel } from "../src/iterui";
// 1) 锁存期间写入按钮真禁用（disabled=true + 原因悬停），解除后恢复原状（原本就禁用的保持禁用）
const mk = (disabled: boolean, title = "") => ({ disabled, title, dataset: {} as any });
const a = mk(false, "下发"), b = mk(true, "无改动");
const root: any = { querySelectorAll: (sel: string) => sel === WRITE_SEL ? [a, b] : [a, b].filter(e => "estop" in e.dataset) };
lockWritesIn(root, true);
assert.equal(a.disabled, true); assert.equal(b.disabled, true); assert.match(a.title, /急停已锁存.*解除/);
lockWritesIn(root, true);  // 重复锁存不覆盖保存的原状
lockWritesIn(root, false);
assert.equal(a.disabled, false); assert.equal(a.title, "下发"); assert.equal(b.disabled, true); assert.equal(b.title, "无改动");
for (const id of ["p-send", "it-go", "fw-flash", "tb-save"]) assert.ok(WRITE_SEL.includes("#" + id), id);
// 2) 屏幕上不出英文状态码 / 来源码
assert.equal(enumZh("running"), "运行中"); assert.equal(enumZh("ESTOP"), "急停");
assert.equal(sourceZh("ui"), "在工作台上按了急停"); assert.equal(sourceZh("weird_x"), "其他来源"); assert.equal(sourceZh(null), "本地服务未上报");
assert.equal(simStartText(3.4), "仿真启动中 · 已 3 s");
// 3) events.md 真实字段：source rule_engine / compare / iterate_status last
assert.match(sourceLabel({ source: "rule_engine" }), /规则/);
const c = toCompare({ round0: { iter: 0, metrics: [{ key: "ss_err", value: 2, unit: "mm" }] }, best: { iter: 3, metrics: [{ key: "ss_err", value: 0.8, unit: "mm" }] }, unchanged: false });
assert.ok(c && c.round0 && c.best);
const m = new IterModel(true);
m.onStatus({ running: false, last: { board: "sim", t: 1, result: { type: "iterate.stopped", reason: "budget", best: { iter: 2, params: {}, pass: false, gaps: {} } } } }, 0);
assert.ok((m.s as any).result, "falls back to last.result");
console.log("r9p3 ok");
