import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cardView, ledgerBest, IterModel } from "../src/iterui";
import { LEDGER, bestValid, fromRoundEvent } from "../src/ledgerbus";
import { toDeclined, declReason, commitResult } from "../src/commitcard";
import { NO_REASON_ZH, USER_DECLINED_ZH, COMMIT_USER_F, MISSING_ZH, COMMIT_STORE_KEY } from "../src/fieldmap";
import { keepPending, dropPending, loadPending } from "../src/commitstore";
import { estopLine, clearStep, estopRestored } from "../src/estop";

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
assert.equal(fromRoundEvent({ iter: 1, valid: true })!.valid, false);   // 没指标不算有效
it.onEvent({ type: "iterate.cleared" }, 2); assert.equal(LEDGER.all().length, 0);

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

// 急停横幅一行；缺字段写「后端未给」，不编；从上次恢复不用本地时刻
const t = new Date(2026, 9, 31, 9, 5).getTime();
assert.equal(estopLine({ source: "heartbeat_lost", at_ms: t, reason_zh: "心跳超时", measured_ms: 1001, threshold_ms: 1000 }, {}, null).line, "09:05 心跳超时 1001 ms（阈值 1000 ms），已锁存");
assert.equal(estopLine({ kind: "watchdog", at_ms: t, reason_zh: "心跳超时" }, {}, null).line, `09:05 心跳超时 ${MISSING_ZH} ms（阈值 ${MISSING_ZH} ms），已锁存`);   // 该有的字段缺了才写后端未给
assert.equal(estopLine({}, { estop_cause: { cause: "firmware:hb_timeout", message_zh: "心跳超时" }, measured_ms: 1200, threshold_ms: 1000 }, null).line, `${MISSING_ZH} 心跳超时 1200 ms（阈值 1000 ms），已锁存`);
// 手动急停：只有时间 + 手动急停，没有间隔 / 阈值槽
assert.equal(estopLine({ source: "ui", reason_zh: "手动急停：上位机发出急停指令" }, {}, t).line, "09:05 手动急停，已锁存");
const mr = estopLine({ source: "ui", restored: true }, {}, t); assert.equal(mr.line, `${MISSING_ZH} 手动急停，已锁存`); assert.ok(mr.restored);
// 未知原因：只显示原因
assert.equal(estopLine({ source: "firmware:overcurrent", reason_zh: "过流" }, {}, t).line, "09:05 过流，已锁存");
const miss = estopLine({}, {}, null).line;
assert.equal(miss, `${MISSING_ZH} ${MISSING_ZH}，已锁存`);
assert.ok(estopLine({}, {}, t).line.startsWith("09:05 "));
const rest = estopLine({ source: "latch_restored" }, {}, t);
assert.ok(rest.restored); assert.ok(rest.line.startsWith(MISSING_ZH));
assert.ok(estopRestored({ restored: true }));
assert.ok(estopLine({}, { estop_cause: { message_zh: "固件报过流" } }, null).line.includes("固件报过流"));
// 解除两步确认
let s1 = clearStep("idle", "clear"); assert.deepEqual(s1, { state: "confirm", send: false });
assert.deepEqual(clearStep(s1.state, "clear"), { state: "idle", send: true });
assert.deepEqual(clearStep("confirm", "cancel"), { state: "idle", send: false });
assert.deepEqual(clearStep("confirm", "timeout"), { state: "idle", send: false });

// #76 等宽数字类一律 ≥16px（.mono 默认 14px 的老问题）
const css = readFileSync("src/style.css", "utf8");
assert.match(css, /\.mono,\.num[^{]*\{font-size:max\(16px,var\(--t-sm\)\)\}/);
assert.match(css, /\.gd li \.n,\.ag-guide \.n\{font-size:16px/);
// 通用：不出现例题名
for (const f of ["ledgerbus.ts", "commitstore.ts"]) assert.doesNotMatch(readFileSync("src/" + f, "utf8"), /car_2wd|motor_pos|2026[A-Z]/);
console.log("✓ r9g：#76 字号 / #101 台账同源 / #110 取消原因 / #111 刷新恢复 / 急停横幅");
