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
// #71 reason=state 即便 ok:true 也算被拒
import { paramRejected, linkTag, rejectHint } from "../src/batch1";
assert.equal(paramRejected({ ok: true, reason: "state", applied: 1 }), true);
assert.equal(paramRejected({ ok: true, status: "clamped", reason: "range", applied: 1 }), false);
assert.equal(paramRejected({ ok: true, applied: 1 }), false);
assert.match(rejectHint({ reason: "state", requested: 2, current: 1 }), /当前状态不允许改.*板上仍为 1/);
// #72 报错正文无原始英文，原文只在详情；有 fix_action 就有按钮
import { errParts, partsHtml } from "../src/errors";
const h = errParts({ code: "E_STATE", message: "param write rejected: state" });
assert.ok(!/[A-Za-z_]{3,}/.test(h.what + h.why + h.fix), JSON.stringify(h)); assert.match(h.raw, /E_STATE/);
const html = partsHtml(h, s => s, "<wa-button class=\"fx\">去处理</wa-button>");
assert.ok(html.indexOf("fx") < html.indexOf("<details"), "按钮在详情外、默认可见");
// #73 本地服务断了绝不显示已连接
assert.equal(linkTag({ board: "connected" }, null, 0, null, false).text, "本地服务未连接");
assert.equal(linkTag({ board: "connected" }, null, 0, null, true).text, "已连接");
// #75 结果卡 / 台账 / 建议卡同一结论源
import { setVerdict, getVerdict, ledgerJudge } from "../src/verdictbus";
setVerdict({ v: "unknown", text: "未判定" });
assert.equal(ledgerJudge(true, "未过"), "未判定"); assert.equal(ledgerJudge(false, "未过"), "未过"); assert.equal(getVerdict()!.text, "未判定");
console.log("r9p3 steering ok");
// 结果卡标题不得在未判定时出现「达标」；依据不重复
import { cardView } from "../src/iterui";
const cv = cardView({ type: "iterate.stopped", reason: "pass", best: { iter: 0, params: { kp: 1 }, pass: true, gaps: {} }, ss_err: { measured: 1, unit: "deg", band: null, inside: null, note_zh: "" }, pass_basis: "按默认 2% 判定", message_zh: "连续 2 轮达标", compare: { round0: [], best: [], unchanged: true, note: "初值已达标，未改参" } } as any);
assert.ok(!/达标/.test(cv.title + cv.reason), cv.title + cv.reason);
assert.equal((cv.verdict.text.match(/按默认 2% 判定/g) ?? []).length <= 1, true, cv.verdict.text);
console.log("r9p3 card ok");
import { boardName, SIDECAR_DOWN } from "../src/batch1";
assert.equal(boardName("sim:motor_pos"), "仿真 · 电机位置环"); assert.ok(!/[a-z_]{3,}/.test(boardName("sim:zzz_unknown")));
assert.ok(!/python|dzbench/.test(SIDECAR_DOWN.what + SIDECAR_DOWN.why + SIDECAR_DOWN.fix)); assert.match(SIDECAR_DOWN.raw, /python -m dzbench/);
console.log("r9p4 ok");
// r9p4 左栏勾只认接口 + 当前项目
import { tickable } from "../src/progress";
assert.equal(tickable({ inferred: true, project: "x" }), false); assert.equal(tickable({ project: null }), false); assert.equal(tickable({ project: "p1" }), true);
// r9p4 结果卡：标题=结论；对比只三项；依据/停止原因进详情；唯一主按钮
import { resultCardHtml } from "../src/iterui";
const rc = resultCardHtml({ type: "iterate.stopped", reason: "pass", message_zh: "连续 2 轮达标", best: { iter: 3, params: { kp: 1, kd: 0.1 }, pass: true, gaps: {} }, verdict: { v: "unknown", zh: "未判定" }, pass_basis: "按默认 2% 判定",
  compare: { round0: [{ key: "overshoot_pct", value: 20, unit: "%" }, { key: "settling_s", value: 3, unit: "s" }, { key: "ss_err", value: 2, unit: "deg" }, { key: "rise_s", value: 1, unit: "s" }], best: [{ key: "overshoot_pct", value: 5, unit: "%" }, { key: "settling_s", value: 1, unit: "s" }, { key: "ss_err", value: 1, unit: "deg" }, { key: "rise_s", value: 1, unit: "s" }], unchanged: false } } as any, s => s, { canApply: true, applyReady: true });
assert.match(rc, /<h4[^>]*>未判定<\/h4>/); assert.equal((rc.match(/class="rc-m"/g) ?? []).length, 3, rc);
const [top, det] = rc.split('<details class="rc-det">'); assert.ok(!/停止原因|判定依据|按默认/.test(top), top); assert.match(det, /停止原因/);
assert.equal((rc.match(/variant="brand"/g) ?? []).length, 1); assert.match(rc, /采用这组参数/);
console.log("r9p4 card ok");
