import assert from "node:assert";
import { readFileSync } from "node:fs";
import { runSelfcheck, selfcheckHtml, parseSelf, lastResortZh, fixGuideZh, fileZh } from "../src/selfcheck";
import { SELFCHECK_F } from "../src/fieldmap";
import { mcExtrasHtml, metricCardHtml } from "../src/metriccard";
import { resultCardHtml } from "../src/iterui";
(async () => {
const rep = { ok: false, items: [{ file: "docs/dev/roles.json", status: "ok", message_zh: "正常", fix_action: "" }, { file: "C:\\x\\reason_codes.json", status: "missing", message_zh: "原因表没装上", fix_action: "reinstall" }] };
// 连着 → 走 op；一行一项；修复按钮；不出现文件名 / 命令
let ops: string[] = [];
let r = await runSelfcheck({ connected: true, call: async op => { ops.push(op); return rep; }, invoke: async () => { throw 0; } });
assert.deepEqual(ops, ["selfcheck_data"]); assert.equal(r.src, "service");
let h = selfcheckHtml(r);
assert.equal((h.match(/<tr class="sc-/g) ?? []).length, 2);
assert.match(h, /角色表<\/td><td>正常/); assert.match(h, /原因表<\/td><td>缺失<\/td><td>原因表没装上/); assert.match(h, /data-sc-fix="reinstall">重新安装/);
assert.doesNotMatch(h, /\.json|python|\.exe|\.py|\.bat|selfcheck/);
assert.match(fixGuideZh("reinstall"), /重新安装/); assert.equal(fileZh("x/unknown.json"), "数据文件");
// 模拟器不认这个 op → 中文错误，再试本机
ops = [];
r = await runSelfcheck({ connected: true, call: async () => { throw { code: "unknown_op", message: "unknown op" }; }, invoke: async cmd => { ops.push(cmd); return JSON.stringify(rep); } });
assert.equal(r.src, "local"); assert.deepEqual(ops, ["run_selfcheck"]); assert.match(r.error!, /本地服务不支持自检/); assert.match(selfcheckHtml(r), /本机自检/);
r = await runSelfcheck({ connected: true, call: async () => { throw { message_zh: "未知操作" }; }, invoke: null });
assert.equal(r.src, "none"); assert.match(r.error!, /^未知操作。请运行/);
// 未连接 → 本机；本机也不行 → 菜单提示（按平台，不带文件名）
r = await runSelfcheck({ connected: false, call: async () => { throw new Error("不该调"); }, invoke: async () => rep });
assert.equal(r.src, "local"); assert.equal(r.error, undefined);
r = await runSelfcheck({ connected: false, call: async () => rep, invoke: async () => { throw "no_script"; } });
assert.equal(r.src, "none"); assert.match(selfcheckHtml(r), /没能运行自检/);
assert.equal(lastResortZh("Mozilla/5.0 (Windows NT 10.0)"), "请运行开始菜单里的『芯台 自检』");
assert.match(lastResortZh("Mozilla/5.0 (X11; Linux)"), /应用菜单里的『芯台 自检』/); assert.doesNotMatch(lastResortZh("Linux"), /\.|python/);
assert.equal(parseSelf("not json"), null); assert.equal(parseSelf({ ok: true }), null);
// Tauri：只开放 run_selfcheck，脚本 / 解释器路径与 fieldmap 一致，不接受参数
const rs = readFileSync("../src-tauri/src/main.rs", "utf8"), cap = JSON.parse(readFileSync("../src-tauri/capabilities/default.json", "utf8")), br = readFileSync("../src-tauri/build.rs", "utf8");
assert.ok(rs.includes(`SELFCHECK_SCRIPT_WIN: &str = "${SELFCHECK_F.scriptWin}"`) && rs.includes(`SELFCHECK_PY_WIN: &str = "${SELFCHECK_F.pyWin}"`) && rs.includes(`SELFCHECK_SH: &str = "${SELFCHECK_F.sh}"`));
const fnBody = rs.slice(rs.indexOf("fn run_selfcheck"), rs.indexOf("fn main()"));
assert.doesNotMatch(fnBody, /python3|\.venv|\bwhich\b|var(_os)?\("PATH"/);   // 不在应用里找解释器
assert.match(rs, /fn run_selfcheck\(\) -> Result<String, String>/);
assert.deepEqual(cap.permissions, ["core:default", "allow-run-selfcheck"]); assert.match(br, /commands\(&\["run_selfcheck"\]\)/);
assert.doesNotMatch(rs, /\.bat/);
// 面向用户的提示里没有命令行（命令只在开发模式拼）
assert.doesNotMatch(readFileSync("src/datatables.ts", "utf8").replace(/^.*DATA_FIX_DEV.*$/gm, ""), /python -m/);
// 指标卡：原因证据列表（不挑一个）、未改参 + 余量、停止原因
const mc = (o: any) => ({ metrics_card: { task_kind: "control", items: [{ name: "超调", verdict: "pass", target: { cmp: "<=", threshold: 5, unit: "%" }, measured: { value: 3, unit: "%" }, margin: 2 }, { name: "调节", verdict: "pass", margin: { value: 0.3, unit: "s" } }], ...o } });
h = mcExtrasHtml(mc({ causes: [{ code: "sat_a", evidence: "strong", basis_zh: "输出贴限幅 80%" }, { code: "sat_b", evidence: "weak", basis_zh: "相位滞后" }], verdict_zh: "可能是 A 或 B" }));
assert.match(h, /可能是 A 或 B/); assert.equal((h.match(/<li>/g) ?? []).length, 2); assert.match(h, /证据强[\s\S]*输出贴限幅 80%[\s\S]*证据弱[\s\S]*相位滞后/);
h = metricCardHtml(mc({ unchanged: true }));
assert.match(h, /初值已满足题面，本次没有改动参数/); assert.match(h, /超调：余量 2%/); assert.match(h, /调节：余量 0\.3 s/);
assert.doesNotMatch(h, /mc-sum|调好|成功|最好一组/);
const rr: any = { reason: "budget_rounds", verdict: { v: "pass" }, best: { params: { a: 1 }, metrics: {} }, ...mc({ unchanged: true }) };
assert.doesNotMatch(resultCardHtml(rr, s => s, { canApply: true, applyReady: true }), /id="it-write"/);
const st = (o: any) => mcExtrasHtml(mc(o)).match(/<p class="mc-stop"[^>]*>([^<]*)/)![1];
const zs = ["converged", "budget_exhausted", "at_limit"].map(c => st({ stop_reason: c }));
assert.equal(new Set(zs).size, 3); zs.forEach(z => assert.doesNotMatch(z, /[a-z_]{4,}/));
assert.equal(st({ stop_reason: "at_limit", stop_reason_zh: "后端说的" }), "后端说的");
console.log("r9q ok");
})().catch(e => { console.error(e); process.exit(1); });
