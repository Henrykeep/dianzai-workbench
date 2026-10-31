import { retryText, clearsRetry, LOCAL_LABEL } from "../src/llmretry";
import { toRetry, isRetry, toSsErr, passBasis, RETRY_F } from "../src/fieldmap";
import { bandLines, cardView, IterModel } from "../src/iterui";
const eq = (a: unknown, b: unknown, m: string) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${m}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`); };
// llm_retry（events.md 定稿字段 attempt/max/wait_s/fix_action）
const r = toRetry({ type: "llm_retry", attempt: 2, max: 4, wait_s: 1.6, code: 503, fix_action: "switch_local_model", message_zh: "x" });
eq(retryText(r), "模型服务繁忙，第 2/4 次重试，约 2 s", "retry text");
eq([r.fix, isRetry({ type: RETRY_F.type })], [RETRY_F.localFix, true], "retry adapter");
eq(retryText(toRetry({ type: "llm_retry", attempt: 1, max: 4 })), "模型服务繁忙，第 1/4 次重试", "no wait");
eq(LOCAL_LABEL, "切到本地模型", "label");
eq([clearsRetry("agent_delta"), clearsRetry("agent_error"), clearsRetry("agent_tool")], [true, true, false], "clear on success");
// ss_err
const card = (ss: any, extra: any = {}) => ({ type: "agent_action", id: 7, tool: "iterate_apply_best", args: { params: { kp: 1 }, ss_err: ss, ...extra } });
const ok = { measured: 0.4, unit: "cm", band: { limit: 1, unit: "cm", item: "B3", source: "题目 B3：误差 ≤ 1cm" }, inside: true, note_zh: "仿真标称换算，未实机标定" };
eq(bandLines(toSsErr(card(ok))), ["稳态误差 实测 0.4 cm / 题目误差带 ≤ 1 cm · 在带内", "误差带来源：题目 B3：误差 ≤ 1cm", "仿真标称换算，未实机标定"], "in band + note");
eq(bandLines(toSsErr(card({ ...ok, measured: 3, inside: false, note_zh: "" })))[0].endsWith("超出误差带"), true, "out of band");
const mis = { measured: 12, unit: "px", band: { limit: 1, unit: "cm", source: "题目" }, inside: null, note_zh: "单位对不上，需先标定（#51）" };
eq(bandLines(toSsErr(card(mis))), ["稳态误差 实测 12 px / 题目误差带 ≤ 1 cm · 单位不一致，需先标定", "误差带来源：题目", "单位对不上，需先标定（#51）"], "unit mismatch");
eq(toSsErr({ args: {} }), null, "absent");
// 卡 + stopped 合成；inside=null 时不出“达标”；pass_basis 跟在达标后
const M = new IterModel(true);
M.onEvent({ type: "iterate.stopped", reason: "pass", message_zh: "连续 2 轮达标", best: { iter: 0, params: { kp: 1 }, pass: { all: true } } }, 0);
M.onEvent(card(mis), 0);
let v = cardView((M.s as any).result);
eq(v.gaps.some(g => g.includes("达标")), false, "no pass when units mismatch");
const M2 = new IterModel(true);
M2.onEvent({ type: "iterate.stopped", reason: "pass", best: { iter: 0, params: { kp: 1 }, pass: { all: true } } }, 0);
M2.onEvent(card(ok, { pass_basis: "按默认 2% 判定，题目误差带待标定" }), 0);
v = cardView((M2.s as any).result);
eq(v.verdict.text, "未判定（按默认 2% 判定，题目误差带待标定）", "pass_basis next to verdict, no verdict → 未判定");
eq(v.reason.includes("判定"), false, "pass_basis only on verdict line, not on reason");
eq(cardView({ reason: "pass", best: { iter: 0, params: { kp: 1 }, pass: { all: true } } }).verdict.text, "未判定", "basis optional");
eq(passBasis({ pass_basis: "a" }), "a", "basis adapter");
const M3 = new IterModel(true); M3.onEvent(card(mis), 0);
eq([M3.s.phase, M3.applyId(), cardView((M3.s as any).result).params], ["done", 7, [["kp", "1"]]], "card without iterate.stopped (tune autopilot)");
console.log("✓ r9 llm_retry / ss_err / pass_basis");
