import assert from "node:assert";
import { readFileSync } from "node:fs";
import { estopLine } from "../src/estop";
import { toVerdict, ampLine } from "../src/fieldmap";
import { cardView, resultCardHtml, stopReasonZh } from "../src/iterui";
import { fromRoundEvent } from "../src/ledgerbus";
import { roleCardHtml, roleLeft, roleReply, collectRoles, toRoleReq, roleCellHtml as rc } from "../src/roles";
import { commitCardHtml, toCommitReq } from "../src/commitcard";
import { statusWords } from "../src/r9p6";
const css = readFileSync("src/style.css", "utf8"), tok = readFileSync("src/tokens.css", "utf8");
// #130 首页连接中标签 ≥16px
assert.match(css, /\.ltag,\.dtag\{[^}]*font-size:16px;font-variant-numeric:tabular-nums/);
// #131 真实无效轮数；只有真发散才说发散；中止带后端原因
const R = (n: number, x: any = {}) => fromRoundEvent({ iter: n, run_id: "q", overshoot_pct: 1, ...x })!;
const one = [R(1, { valid: false, status: "aborted", reason_zh: "用户停止" })];
assert.equal(stopReasonZh({ reason: "invalid", run_id: "q" } as any, one), "1 轮无效");
assert.equal(stopReasonZh({ reason: "invalid", run_id: "q" } as any, [R(1), R(2, { valid: false }), R(3, { valid: false })]), "连续 2 轮无效");
assert.equal(stopReasonZh({ reason: "invalid", invalid_streak: 4 } as any, one), "连续 4 轮无效");
assert.equal(cardView({ reason: "invalid", run_id: "q", best: null } as any, one).title, "没有可用的一轮");
assert.equal(cardView({ reason: "invalid", run_id: "q", best: null } as any, [R(1, { diverged: true })]).title, "发散，未找到稳定参数");
assert.equal(cardView({ reason: "invalid", run_id: "q", best: null } as any, [R(1, { sensor_sat: true })]).title, "发散，未找到稳定参数");
assert.equal(cardView({ reason: "diverged", run_id: "q", best: null } as any, []).title, "发散，未找到稳定参数");
assert.equal(cardView({ reason: "pass", run_id: "q", best: { iter: 1, params: { a: 1 } } } as any, one).title, "没有可用的一轮");   // 中止的轮不是发散
assert.equal(stopReasonZh({ reason: "aborted", reason_zh: "上位机断开" } as any, []), "中止（上位机断开）");
assert.equal(stopReasonZh({ reason: "stopped" } as any, []), "中止");
assert.equal(R(1, { status: "aborted" }).state, "aborted"); assert.equal(R(1, { diverged: true }).state, "diverged");
// #134 琥珀 --warn（两套主题都来自 --warning），partial 卡写幅度、不写「最好一组 / 达标」
assert.match(tok, /--warn:var\(--warning\);/); assert.match(tok, /--warning:#9A5B00/); assert.match(tok, /--warning:#F5B544/);
const ev = { reason: "pass", rounds: 1, best: { iter: 0, params: { kp: 1 } }, verdict: "partial", verdict_zh: "未验题面幅度", amp_reduced: true, amp_spec: 1.0, amp_tested: 0.5, amp_unit: "m", warning_zh: "按降幅测试，未验题面幅度", message_zh: "已达标" };
const r: any = { ...ev, verdict: toVerdict(ev) };
assert.equal(ampLine(ev), "题面幅度 1 m，实测幅度 0.5 m");
const v = cardView(r, []); assert.equal(v.title, "题面幅度 1 m，实测幅度 0.5 m"); assert.ok(!v.reason.includes("达标"));
const h = resultCardHtml(r, s => s, { canApply: true, applyReady: true });
assert.ok(h.includes("题面幅度 1 m，实测幅度 0.5 m") && h.includes("按降幅测试，未验题面幅度"));
for (const bad of ["初值已是最好一组", "最好一组", "通过", "达标"]) assert.ok(!h.includes(bad), bad);
assert.equal((h.match(/题面幅度 \d/g) || []).length, 1);
assert.equal(ampLine({}), "");
// #135 角色卡：缺几个就灰 + 提示；发送中立刻灰；回执
const rq = toRoleReq({ fix_action: "confirm_roles", missing: ["a", "b", "c"], suggested: { a: "P" }, reason_zh: "x" })!;
assert.equal(roleLeft(rq, {}), 2); assert.equal(roleLeft(rq, { b: "I", c: "D" }), 0);
const h0 = roleCardHtml(rq, { phase: "idle", left: 2 }); assert.ok(h0.includes("还有 2 个参数未选角色") && /id="role-ok" disabled/.test(h0));
assert.ok(!/disabled/.test(roleCardHtml(rq, { phase: "idle", left: 0 })));
const hs = roleCardHtml(rq, { phase: "sending", left: 0 }); assert.ok(/disabled>已发出，等后端结果/.test(hs));
assert.deepEqual(roleReply({ ok: true, roles: { a: "P" } }), { phase: "sent", left: 0 });
assert.deepEqual(roleReply({ ok: false, message_zh: "角色冲突", fix_action: "confirm_roles" }), { phase: "error", left: 0, msg: "角色冲突" });
assert.ok(roleCardHtml(rq, { phase: "error", left: 0, msg: "角色冲突" }).includes("角色冲突"));
assert.ok(roleCardHtml(rq, { phase: "sent", left: 0 }).includes("重试整定"));
assert.deepEqual(collectRoles(rq, { b: "I", c: "LIM" }), { a: "P", b: "I", c: "LIM" });
const main = readFileSync("src/main.ts", "utf8");
assert.match(main, /if \(roleUi\.phase === "sending" \|\| !ROLE_REQ\) return;/); assert.match(main, /ok\.disabled = true; roleUi = \{ phase: "sending"/);
// #133 写入后提示 + 带到待保存卡；卡副标题
const ag = readFileSync("src/agent.ts", "utf8");
assert.match(ag, /written: WRITTEN_ZH/); assert.match(ag, /focusPendingCommit/); assert.match(readFileSync("src/fieldmap.ts", "utf8"), /已写入文件，还没保存到工程版本/);
assert.ok(commitCardHtml(toCommitReq({ request_id: "a", files: [{ path: "x", status: "M" }] }), s => s).includes("把刚写入的文件存成一个版本，可回滚"));
// #132 缺值最多一句
assert.equal(estopLine({ reason: "heartbeat" }, {}).line, "心跳超时（间隔未知），已锁存");
assert.equal(estopLine({ reason: "heartbeat", measured_ms: 2500, threshold_ms: 1500, latched_at: new Date(2026, 0, 1, 1, 2).getTime() }, {}).line, "01:02 心跳超时 2500 ms（阈值 1500 ms），已锁存");
assert.equal(estopLine({ reason: "heartbeat", threshold_ms: 1500 }, {}).line, "心跳超时（间隔未知），已锁存");
for (const x of [{}, { reason: "heartbeat" }, { reason: "manual" }, { reason: "zz" }]) assert.ok(!estopLine(x, {}).line.includes("后端未给"));
// sensor_sat 实时芯片
assert.deepEqual(statusWords({ sensor_sat: true }).flags, ["传感器饱和"]); assert.deepEqual(statusWords({ sensor_sat: false }).flags, []);
console.log("✓ r9i：#130 #131 #132 #133 #134 #135 + sensor_sat");
// #135 用户已选的角色在参数列表重画后仍保留（优先于建议值）
{
  assert.match(rc("b", rq, undefined, { b: "I" }), /value="I" selected/);
  assert.match(rc("a", rq, undefined, { a: "D" }), /value="D" selected/);
  assert.match(rc("c", rq), /value="" selected disabled/);
  assert.match(readFileSync("src/main.ts", "utf8"), /paramRole\], ROLE_PICKS\)/); }
// #134 降幅卡：后端 message_zh 是「初值已是最好一组」也不进原因 / 详情
{ const h2 = resultCardHtml({ ...r, message_zh: "初值已是最好一组" }, s => s, { canApply: true, applyReady: true });
  assert.ok(!h2.includes("初值已是最好一组") && !h2.includes("最好一组")); }
// #131 后端停止码 invalid_streak 同 invalid：用真实计数，不落到「其他（…）」
assert.equal(stopReasonZh({ reason: "invalid_streak", invalid_streak: 2 } as any, []), "连续 2 轮无效");
assert.equal(stopReasonZh({ reason: "invalid_streak", invalid_streak: 1 } as any, []), "1 轮无效");
