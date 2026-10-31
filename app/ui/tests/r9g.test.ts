import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cardView, ledgerBest, IterModel } from "../src/iterui";
import { LEDGER, bestValid, fromRoundEvent } from "../src/ledgerbus";
import { toDeclined, declReason, commitResult } from "../src/commitcard";
import { NO_REASON_ZH, USER_DECLINED_ZH, COMMIT_USER_F, MISSING_ZH, LATCH_AT_MISSING_ZH, COMMIT_STORE_KEY, COMMIT_SENT_ZH, COMMIT_BTN_ZH, NO_STABLE_ZH, VERDICT_ZH, RESULT_CLEAR_EV, PORT_APP_F, toVerdict } from "../src/fieldmap";
import { verdictLine } from "../src/iterui";
import { simPortLabel } from "../src/examples";
import { commitCardHtml, toCommitReq } from "../src/commitcard";
import { keepPending, dropPending, loadPending } from "../src/commitstore";
import { estopLine, clearStep, estopRestored, latchTime } from "../src/estop";

// #101 结果卡和台账同一份数据：台账有有效轮，stopped 没带 best → 卡片给最好的有效一轮，不说“没有可用的一轮”
LEDGER.reset();
const rs = [
  { n: 1, params: { kp: 0.1 }, metrics: { overshoot_pct: 12, settle_ms: 400 }, valid: true },
  { n: 2, params: { kp: 0.2 }, metrics: { overshoot_pct: 3, settle_ms: 300 }, valid: true },
  { n: 3, params: { kp: 0.9 }, metrics: { overshoot_pct: 0 }, valid: false },
];
assert.equal(bestValid(rs)!.n, 2);
const v = cardView({ reason: "pass", best: null }, rs);
assert.notEqual(v.title, "没有可用的一轮");
assert.match(v.title, /第 2 轮/);
assert.deepEqual(v.params, [["kp", "0.2"]]);
assert.equal(cardView({ reason: "pass", best: null }, []).title, "没有可用的一轮");   // 台账真没有有效轮才这么说
assert.equal(ledgerBest({ reason: "pass", best: { iter: 5, params: { kp: 1 } } }, rs)!.iter, 5);   // 后端给了 best 以后端为准
// iterate.round 事件进同一份台账；清空事件一起清
const it = new IterModel(true);
it.onEvent({ type: "iterate.round", iter: 0, valid: true, overshoot_pct: 4, settle_ms: 250, params: { kp: 0.3 } }, 0);
it.onEvent({ type: "iterate.round", iter: 1, valid: false, why_invalid: "x", params: { kp: 9 } }, 1);
assert.equal(LEDGER.all().length, 2); assert.equal(bestValid(LEDGER.all())!.n, 0);
assert.equal(fromRoundEvent({ iter: 1, valid: true })!.valid, false);
void COMMIT_SENT_ZH;   // 没指标不算有效
it.onEvent({ type: "result_reset", run_id: "r1", reason: "iterate_start" }, 2); assert.equal(LEDGER.all().length, 0);
assert.deepEqual([...RESULT_CLEAR_EV], ["result_reset"]); assert.deepEqual([...PORT_APP_F], ["app_name"]);

// #110 原因：reason_zh → message_zh → detail，顶层 / data / error 都找；用户自己取消且后端没给 → 「你已取消写入」
assert.equal(declReason({ reason_zh: "a", message_zh: "b" }), "a");
assert.equal(declReason({ data: { message_zh: "b" } }), "b");
assert.equal(declReason({ error: { detail: "c" } }), "c");
assert.equal(toDeclined({ request_id: 1 }).reason, NO_REASON_ZH);
assert.equal(toDeclined({ request_id: 1, [COMMIT_USER_F]: true }).reason, USER_DECLINED_ZH);
assert.equal(toDeclined({ request_id: 1, [COMMIT_USER_F]: true, data: { reason_zh: "后端说的" } }).reason, "后端说的");
assert.equal(commitResult({ reason: "commit_declined", [COMMIT_USER_F]: true }).decl!.reason, USER_DECLINED_ZH);

// #111 待确认卡存 sessionStorage，按 request_id 去重；出结果就删
const mem = new Map<string, string>(); const st = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
keepPending(st, { type: "commit_confirm_request", request_id: 7, branch: "a" });
keepPending(st, { type: "commit_confirm_request", request_id: 7, branch: "b" });
keepPending(st, { type: "commit_confirm_request", request_id: 8 });
assert.deepEqual(loadPending(st).map(x => [x.request_id, x.branch]), [[7, "b"], [8, undefined]]);
dropPending(st, "7"); assert.deepEqual(loadPending(st).map(x => x.request_id), [8]);
mem.set(COMMIT_STORE_KEY, "{bad"); assert.deepEqual(loadPending(st), []);
const agentSrc = readFileSync("src/agent.ts", "utf8");
assert.match(agentSrc, /loadPending\(ss\)/); assert.match(agentSrc, /dropPending\(ss, id\)/);

// 急停横幅（定稿字段 reason / reason_zh / latched_at / restored / measured_ms / threshold_ms / fix_action）
const t = new Date(2026, 9, 31, 9, 5).getTime();
assert.equal(estopLine({ reason: "heartbeat_lost", latched_at: t, reason_zh: "心跳超时", measured_ms: 1601, threshold_ms: 1500 }, {}).line, "09:05 心跳超时 1601 ms（阈值 1500 ms），已锁存");
assert.equal(estopLine({ reason: "heartbeat_lost", latched_at: t / 1000, reason_zh: "心跳超时", measured_ms: 1601, threshold_ms: null }, {}).line, "09:05 心跳超时 1601 ms（阈值 后端未给），已锁存");   // 数和后端未给不混在一个槽
assert.equal(estopLine({ reason: "watchdog", reason_zh: "心跳超时" }, {}).line, `${LATCH_AT_MISSING_ZH} 心跳超时 ${MISSING_ZH}（阈值 ${MISSING_ZH}），已锁存`);
assert.equal(estopLine({ reason: "heartbeat_lost", cause: { value: 999 }, reason_zh: "x" }, {}).line.includes("999"), false);   // cause.value 不读
// #120 手动急停：只一行「HH:MM 手动急停，已锁存」，原因不重复，无间隔 / 阈值槽
assert.equal(estopLine({ reason: "manual", latched_at: t, reason_zh: "手动急停：上位机发出急停指令" }, {}).line, "09:05 手动急停，已锁存");
assert.equal(estopLine({ source: "ui", latched_at: t }, {}).line, "09:05 手动急停，已锁存");
// #119 锁存时刻只认后端 latched_at；从上次恢复
const mr = estopLine({ reason: "manual", restored: true }, {}); assert.equal(mr.line, `${LATCH_AT_MISSING_ZH} 手动急停，已锁存`); assert.ok(mr.restored);
assert.equal(estopLine({}, { estop: { reason: "manual", latched_at: new Date(t).toISOString(), restored: true, fix_action: "estop_clear" } }).fix, "estop_clear");
assert.ok(estopLine({}, { estop: { reason: "manual", latched_at: t, restored: true } }).restored);
assert.equal(latchTime("bad"), null);
// 未知原因：只显示原因
assert.equal(estopLine({ reason: "overcurrent", reason_zh: "过流", latched_at: t, measured_ms: 5 }, {}).line, "09:05 过流，已锁存");
assert.equal(estopLine({}, {}).line, `${LATCH_AT_MISSING_ZH} ${MISSING_ZH}，已锁存`);
const mainSrc = readFileSync("src/main.ts", "utf8"); assert.doesNotMatch(mainSrc, /estopLine\(ev, S\.status, latchAt\)/);
// 解除两步确认
let s1 = clearStep("idle", "clear"); assert.deepEqual(s1, { state: "confirm", send: false });
assert.deepEqual(clearStep(s1.state, "clear"), { state: "idle", send: true });
assert.deepEqual(clearStep("confirm", "cancel"), { state: "idle", send: false });
assert.deepEqual(clearStep("confirm", "timeout"), { state: "idle", send: false });

// #76 等宽数字类一律 ≥16px（.mono 默认 14px 的老问题）
const css = readFileSync("src/style.css", "utf8");
assert.match(css, /\.mono,\.num[^{]*\{font-size:max\(16px,var\(--t-sm\)\)\}/);
assert.match(css, /\.gd li \.n,\.ag-guide \.n\{font-size:16px/);
// #115 只比同一 run_id；manual_step 不算迭代轮
LEDGER.reset();
const xr = [
  { n: 1, params: { kp: 7 }, metrics: { overshoot_pct: 0 }, valid: true, runId: "old" },
  { n: 1, params: { kp: 1 }, metrics: { overshoot_pct: 9 }, valid: true, runId: "new" },
  { n: 1, params: { kp: 5 }, metrics: { overshoot_pct: 0 }, valid: true, kind: "manual_step" },
];
assert.deepEqual(cardView({ reason: "invalid", best: null, run_id: "new" } as any, xr).params, [["kp", "1"]]);
assert.equal(cardView({ reason: "invalid", best: null, run_id: "none" } as any, xr).title, "没有可用的一轮");
// #116 后端 best 指向台账里无效 / 发散的一轮：不显示、不给采用
const bad = [{ n: 3, params: { kp: 99 }, metrics: { overshoot_pct: 0.1 }, valid: false, runId: "r" }];
const vb = cardView({ reason: "diverged", best: { iter: 3, params: { kp: 99 } }, run_id: "r" } as any, bad);
assert.equal(vb.title, NO_STABLE_ZH); assert.equal(vb.canWrite, false); assert.deepEqual(vb.params, []);
assert.equal(fromRoundEvent({ iter: 2, valid: true, diverged: true, overshoot_pct: 1 })!.valid, false);
// #121 verdict=pass 没有 verdict_zh → 通过
assert.equal(toVerdict({ verdict: "pass" }).zh, "通过"); assert.equal(toVerdict({ verdict: "fail" }).zh, "未通过");
assert.equal(verdictLine({ v: "pass", zh: "" }, null, "").text, VERDICT_ZH.pass);
// #122 叫法
const cch = commitCardHtml(toCommitReq({ request_id: "a", files: [{ path: "x", status: "M" }] }), s => s);
assert.ok(cch.includes(COMMIT_BTN_ZH) && !cch.includes("确认提交") && !cch.includes("git 提交"));
for (const f of ["agent.ts", "commitstore.ts", "commitcard.ts"]) assert.doesNotMatch(readFileSync("src/" + f, "utf8"), /对账|确认提交/);
// #117 已点确认的卡：缓存标 sent，恢复时按钮禁用 + 「已发出，等后端结果」
assert.match(agentSrc, /COMMIT_SENT_F\]: true/); assert.match(agentSrc, /COMMIT_SENT_ZH/);
// #104 app_name → app_dir → 目录名
assert.equal(simPortLabel({ port: "sim:abc", app_name: "应用A" } as any), "仿真 · 应用A");
assert.equal(simPortLabel({ port: "sim:abc", app_dir: "apps/abc2" } as any).startsWith("仿真 · "), true);
// #114
assert.ok(css.includes(".dt,.tl-e,.tl-e *,.pdesc,.kk>span.pdesc,.rc-det>p,.acc-sum,.ledger td.hn,#t0-mark{font-size:16px !important}"));
// 通用：不出现例题名
for (const f of ["ledgerbus.ts", "commitstore.ts"]) assert.doesNotMatch(readFileSync("src/" + f, "utf8"), /car_2wd|motor_pos|2026[A-Z]/);
console.log("✓ r9g：#76 字号 / #101 台账同源 / #110 取消原因 / #111 刷新恢复 / 急停横幅");
