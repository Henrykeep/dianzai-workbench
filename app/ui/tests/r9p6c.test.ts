import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { toCommitReq, commitCardHtml, commitOpArgs, toDeclined, declinedHtml, mountCommitCard, showDeclined } from "../src/commitcard";
import { writeScopeNote, WRITE_ONLY_ZH, COMMIT_EV } from "../src/fieldmap";
import { connButton, declaredBoard, boardLabel, portOption, chUnit, shortHint, paramDesc, lifeSummary } from "../src/r9p6c";
import { linkTag } from "../src/batch1";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

// #88 commit_confirm_request → 卡
const req = { type: "commit_confirm_request", request_id: "c-7", branch: "feat/x", files: [{ path: "app.yaml", status: "M" }, { path: "src/<a>.c", status: "A" }], message: "tune: kp 0.5→0.8", message_zh: "把 kp 写回 app.yaml" };
assert.equal(COMMIT_EV.request, req.type);
const c = toCommitReq(req);
assert.deepEqual([c.id, c.branch, c.files.length, c.message, c.messageZh], ["c-7", "feat/x", 2, "tune: kp 0.5→0.8", "把 kp 写回 app.yaml"]);
const h = commitCardHtml(c, esc);
for (const t of ["feat/x", "app.yaml", "src/&lt;a&gt;.c", "修改", "新增", "把 kp 写回 app.yaml", "保存到工程版本", "取消", "2 个文件"]) assert.ok(h.includes(t), t);
assert.ok(!/disabled/.test(h));
assert.match(commitCardHtml(toCommitReq({ files: [{ path: "a" }] }), esc), /data-cc="ok" disabled/, "没有 request_id 不能确认");
assert.deepEqual(commitOpArgs("c-7", true), { op: "commit_confirm", args: { request_id: "c-7", approve: true } });
assert.deepEqual(commitOpArgs("c-7", false).args, { request_id: "c-7", approve: false });

// 点击后两个按钮都禁用，只发一次
{
  const mk = (cc: string) => ({ dataset: { cc }, disabled: false, onclick: null as any });
  const btns = [mk("ok"), mk("cancel")], res = { textContent: "", innerHTML: "" };
  const el: any = { querySelectorAll: () => btns, querySelector: () => res };
  const sent: any[] = [];
  mountCommitCard(el, c, async (op, a) => { sent.push([op, a]); return {}; });
  const pr = btns[1].onclick();
  assert.ok(btns.every(b => b.disabled)); assert.equal(res.textContent, "已取消");
  void pr.then(() => { assert.deepEqual(sent, [["commit_confirm", { request_id: "c-7", approve: false }]]); console.log("r9p6c click ok"); });
}
// commit_declined → reason_zh / 兜底 / fix 按钮走 resolveFix
assert.deepEqual(toDeclined({ request_id: "c-7", reason_zh: "用户超时未确认", fix_action: "ask_user_commit" }), { id: "c-7", reason: "用户超时未确认", fix: "ask_user_commit" });
assert.equal(toDeclined({}).reason, "后端未给原因");
assert.equal(toDeclined({ reason_zh: "  " }).reason, "后端未给原因");
const dh = declinedHtml({ reason: "用户拒绝", fix: "ask_user_commit" }, esc, { kind: "run", label: "回复 Agent 要不要提交" });
assert.match(dh, /未提交：用户拒绝/); assert.match(dh, /data-cc-fix="ask_user_commit"/); assert.ok(!/disabled/.test(dh));
assert.match(declinedHtml({ reason: "x", fix: "zz" }, esc, { kind: "none", label: "暂不可用", note: "无入口" }), /disabled/);
assert.ok(!/data-cc-fix/.test(declinedHtml({ reason: "x", fix: "" }, esc, null)));
{
  const res: any = { innerHTML: "" }, fixBtn: any = { addEventListener: (_: string, f: any) => { fixBtn.f = f; } };
  const btns = [{ disabled: false }, { disabled: false }];
  const act: any = { querySelector: (q: string) => q === ".cc-res" ? res : fixBtn };
  const el: any = { classList: { add() {} }, querySelectorAll: () => btns, querySelector: () => act };
  let ran = "", resolved = "";
  showDeclined(el, { reason: "超时", fix: "ask_user_commit" }, esc, a => { resolved = a; return { kind: "run", label: "回复" }; }, a => { ran = a; });
  fixBtn.f(); assert.equal(ran, "ask_user_commit"); assert.equal(resolved, "ask_user_commit"); assert.ok(btns.every(b => b.disabled)); assert.match(res.innerHTML, /超时/);
}
const prog = readFileSync("src/progress.ts", "utf8"); assert.match(prog, /ask_user_commit:\s*\{/, "fix_action ask_user_commit 有入口");
// 写文件卡 scope
assert.equal(writeScopeNote({ scope: "write_only" }), WRITE_ONLY_ZH);
assert.equal(WRITE_ONLY_ZH, "只授权写入文件，不会存进工程版本（「保存到工程版本」另有确认卡）");
assert.equal(writeScopeNote({}), ""); assert.equal(writeScopeNote({ scope: "commit" }), "");
// 字段名只在 fieldmap
for (const f of ["src/commitcard.ts", "src/agent.ts", "src/projflow.ts", "src/main.ts"]) {
  const t = readFileSync(f, "utf8");
  for (const k of ['"request_id"', '"approve"', '"reason_zh"', '"write_only"', '"commit_confirm_request"', '"commit_declined"', '"scope"']) assert.ok(!t.includes(k), `${f} 写死了 ${k}`);
  // op 名是入口不是字段：按 test_wiring 的约定 call("commit_confirm", …) 以字面量出现在调用处（agent.ts），其余字段名仍只在 fieldmap.ts
  assert.match(readFileSync("src/agent.ts", "utf8"), /call\("commit_confirm", args\)/);
}
console.log("r9p6c commit ok");

// 1) 连接状态同源：按钮跟 linkTag 走
const ok = linkTag({ board: "connected" }, null, 0), off = linkTag({ board: "disconnected", reason: "0" }, null, 0);
assert.equal(connButton(ok).text, "断开连接"); assert.equal(connButton(off).text, "连接"); assert.match(connButton(ok).title, /已连接/);
assert.equal(connButton(linkTag({ board: "connected" }, null, 0, null, false)).text, "连接", "本地服务没了按钮也不说已连");
const main = readFileSync("src/main.ts", "utf8");
assert.ok(!/st\.connected \? "断开/.test(main), "按钮不再看另一份状态");
// 2) 板子名
assert.equal(declaredBoard({ title: "恒温箱" }, { name: "p" }), "恒温箱");
assert.equal(declaredBoard({}, { name: "我的工程" }), "我的工程");
assert.equal(declaredBoard({ path: "/x/apps/fan_ball/app.yaml" }, null), "fan_ball");
assert.equal(declaredBoard({}, null), "");
assert.equal(portOption("sim:randplant-7", "恒温箱"), "仿真 · 恒温箱");
assert.equal(portOption("sim:randplant-7", ""), "仿真");
assert.ok(!/仿真.*仿真/.test(portOption("sim:x", "")) && !/仿真板/.test(portOption("sim:x", "")));
assert.equal(boardLabel("sim:x", ""), "", "底栏已有「仿真」标签，不再重复");
assert.equal(boardLabel("COM3", ""), "串口 COM3");
// 3) 单位同源
const cal = new Map([["spd", { unit: "cm/s" }]]);
assert.equal(chUnit({ name: "spd", unit: "rps" }, cal), "cm/s"); assert.equal(chUnit({ name: "t", unit: "%RH" }, cal), "%RH"); assert.equal(chUnit({ name: "t" }, cal), "");
assert.ok(!/f\.unit \? `<small>/.test(main), "读数单位不再绕过标定单位");
assert.ok(!/cm\/s|rps/.test(readFileSync("src/plot.ts", "utf8").replace(/\/\/.*$/gm, "")), "轴单位不写死");
// 4) 截断
const sh = shortHint(["本地服务提示：一句非常非常非常长的话需要截断显示", "另有 2 个窗口连着"]);
assert.ok(sh.text.length <= 24); assert.match(sh.title, /另有 2 个窗口/); assert.match(sh.text, /（\+1）/);
assert.deepEqual(shortHint(["", ""]), { text: "", title: "" });
assert.equal(paramDesc({ desc: " 轮速 PI 比例 " }), "轮速 PI 比例"); assert.equal(paramDesc({}), "");
const html = readFileSync("index.html", "utf8"); const ph = /id="p-q"[^>]*placeholder="([^"]+)"/.exec(html)![1]; assert.ok(ph.length <= 10, "筛选框占位够短：" + ph);
// 5) 参数区一个状态标签
assert.equal(lifeSummary(2, 1, 0).text, "2 项待下发"); assert.equal(lifeSummary(0, 3, 1).text, "已下发 · 未保存"); assert.equal(lifeSummary(0, 0, 0).text, "与默认一致");
assert.equal(lifeSummary(0, 0, 4).rows.length, 5);
assert.match(html, /<div class="life" id="life"><span id="life-tag"[^>]*role="button"/); assert.match(html, /id="life-rows" hidden/);
// 随机：任何组合标签都只有一个短句
for (let i = 0; i < 200; i++) { const s = lifeSummary(Math.floor(Math.random() * 30), Math.floor(Math.random() * 30), Math.floor(Math.random() * 30)); assert.ok(s.text.length <= 10 && !s.text.includes("·  ·")); }
console.log("r9p6c review ok");
// #88 定稿（后端 tests/test_git_confirm.py 同名字段）：status pending → committed / rejected / failed
import { commitResult, committedHtml } from "../src/commitcard";
{
  assert.equal(commitResult({ request_id: "c", status: "pending" }).state, "pending");
  assert.deepEqual(commitResult({ ok: true, status: "committed", commit: "ab12cd3" }), { state: "committed", commit: "ab12cd3" });
  assert.equal(commitResult({ type: "commit_confirm_request", request_id: "c", status: "committed" }).state, "committed");
  const d = commitResult({ ok: false, reason: "commit_declined", reason_zh: "用户拒绝提交", fix_action: "ask_user_commit", request_id: "c" });
  assert.equal(d.state, "rejected"); assert.equal(d.decl!.reason, "用户拒绝提交"); assert.equal(d.decl!.fix, "ask_user_commit");
  assert.equal(commitResult({ status: "rejected" }).decl!.reason, "后端未给原因");
  const f = commitResult({ ok: false, reason: "commit_failed", reason_zh: "pre-commit 钩子失败" });
  assert.equal(f.state, "failed"); assert.equal(f.decl!.reason, "pre-commit 钩子失败");
  assert.equal(commitResult({ status: "failed" }).state, "failed");
  assert.match(committedHtml("ab12cd3", esc), /已提交 <span class="mono">ab12cd3/);
  assert.match(declinedHtml({ reason: "x", fix: "" }, esc, null), /未提交：x/);
  const yml = readFileSync("../../docs/dev/entrypoints.yaml", "utf8");
  assert.ok(!/^\s+commit_confirm:/m.test(yml), "commit_confirm 不在 script_ops");
  assert.match(yml, /ops: \[[^\]]*commit_confirm[^\]]*\]/, "commit_confirm 已登记到界面动作");
  console.log("r9p6c status ok");
}
// #80 去写死：例题候选只来自后端端口列表，板名只来自声明
import { exampleCandidates, simBoardZh } from "../src/examples";
import { forkFirstExample } from "../src/pjask";
{
  assert.deepEqual(exampleCandidates([{ port: "COM3", kind: "serial" }, { port: "sim:aa" }, { port: "sim:aa+hw" }, { port: "sim:bb" }]), ["aa", "bb"]);
  assert.equal(simBoardZh(""), "仿真板"); assert.equal(simBoardZh(" 风扇 "), "风扇");
  const src = readFileSync("src/examples.ts", "utf8") + readFileSync("src/pjask.ts", "utf8");
  assert.ok(!/\d{4}[A-Z]_|motor_|ball/.test(src), "不写死例题名");
  const tried: string[] = [];
  forkFirstExample(async (_op, a) => { tried.push(a.example); if (a.example === "aa") throw { code: "bad_example" }; return { message_zh: "已基于 bb 新建 p1" }; }, ["aa", "bb"])
    .then(m => { assert.deepEqual(tried, ["aa", "bb"]); assert.equal(m, "已基于 bb 新建 p1"); console.log("r9p6c #80 ok"); });
  forkFirstExample(async () => { throw { code: "bad_example" }; }, []).then(m => assert.match(m, /没有找到内置示例/));
}
// fw-plant a4161a3：plant.estimate / basis 标签；粗估模型下的结果标「仅仿真粗估」；单位原样
import { toPlant, plantTagHtml, isCoarse, coarseTagHtml } from "../src/plant";
import { resultCardHtml } from "../src/iterui";
import { metricCardHtml } from "../src/metriccard";
import { toMetricsCard } from "../src/fieldmap";
{
  const c = toPlant({ plant: { order: 1, unit: "°C", u_unit: "%", estimate: "coarse", basis: "题面(2)：加热 60 s 升 10 °C" } })!;
  assert.equal(c.tag, "粗估");
  const h = plantTagHtml(c, esc);
  assert.match(h, /对象模型：粗估 · % → °C/); assert.match(h, /title="题面\(2\)：加热 60 s 升 10 °C"/); assert.match(h, /warn-t/);
  const i = toPlant({ estimate: "identified", basis: "data/id_0412.csv", unit: "rpm" })!;
  assert.match(plantTagHtml(i, esc), /对象模型：已辨识 · rpm/);
  assert.match(plantTagHtml(toPlant({ estimate: "identified" }), esc), /title="后端未给依据"/);
  assert.equal(toPlant({ plant: { unit: "m" } }), null); assert.equal(plantTagHtml(null, esc), "");
  const mc = (est: string, basis = "题面(2)粗估") => ({ metrics_card: { task_kind: "control", items: [{ name: "温度稳态误差", verdict: "pass", model: { estimate: est, basis } }, { name: "超调", verdict: "pass" }] } });
  assert.ok(isCoarse(mc("coarse")) && !isCoarse(mc("identified")) && !isCoarse({}) && !isCoarse({ plant: { estimate: "coarse" } }));
  assert.match(coarseTagHtml(mc("coarse")), /title="题面\(2\)粗估">仅仿真粗估/); assert.equal(coarseTagHtml(mc("identified")), "");
  assert.match(coarseTagHtml(mc("coarse", "")), /title="后端未给依据"/);
  const card = (x: any) => resultCardHtml({ reason: "pass", verdict: "pass", verdict_zh: "达标", ...x } as any, esc, { canApply: false, applyReady: false });
  assert.match(card(mc("coarse")), /仅仿真粗估/); assert.ok(!/仅仿真粗估/.test(card(mc("identified")))); assert.ok(!/仅仿真粗估/.test(card({})));
  const mh = metricCardHtml(mc("coarse"));
  assert.equal((mh.match(/仅仿真粗估/g) ?? []).length, 1, "只标 model=coarse 的那一项");
  assert.ok(!/仅仿真粗估/.test(metricCardHtml(mc("identified"))));
  assert.equal(toMetricsCard(mc("coarse"))!.items[0].model!.basis, "题面(2)粗估"); assert.equal(toMetricsCard(mc("coarse"))!.items[1].model, null);
  for (const f of ["src/plant.ts", "src/main.ts", "src/iterui.ts", "src/metriccard.ts"]) assert.ok(!/"(estimate|basis|model|plant_estimate|plant_coarse)"/.test(readFileSync(f, "utf8")), f + " 不写字段名");
  console.log("r9p6c plant ok");
}
// r9d：#91 stop_iteration 有修复按钮；进度块 detail（中文）优先；写文件卡按钮只叫「确认写入」
import { ACTIONS as ACT2, resolveFix as rf2 } from "../src/progress";
{
  assert.equal(ACT2.stop_iteration.ui, "it-go"); assert.equal(ACT2.stop_iteration.when, "cancel"); assert.ok(rf2("stop_iteration"));
  const ag = readFileSync("src/agent.ts", "utf8"); assert.ok(!ag.includes("确认并提交") && ag.includes("确认写入"));
  assert.match(readFileSync("src/progress.ts", "utf8"), /s\.detail \? "：" \+ s\.detail/);
  console.log("r9p6c r9d ok");
}
// #104 下拉框仿真项：应用名来自 list_ports（暂定字段），否则目录名；绝不显示通用「仿真板」
import { simPortLabel } from "../src/examples";
import { IterModel as IM } from "../src/iterui";
{
  assert.equal(simPortLabel({ port: "sim:d_press", kind: "sim" }), "仿真 · d_press");
  assert.equal(simPortLabel({ port: "sim:d_press", kind: "sim", app_name: "压力控制" }), "仿真 · 压力控制");
  assert.equal(simPortLabel({ port: "sim:rp13+hw", kind: "sim", name: " " }), "仿真 · rp13（当实板）");
  assert.equal(simPortLabel({ port: "COM3" }), "");
  for (const id of ["a", "b_c", "x9"]) assert.ok(!simPortLabel({ port: "sim:" + id }).includes("仿真板"));
  assert.match(readFileSync("src/main.ts", "utf8"), /simPortLabel\(p as any\)/);
  // #101 清结果卡：后端清除事件 / 新一轮开始 都清；重连只恢复属于当前板的结果
  const it = new IM();
  it.onEvent({ type: "iterate.stopped", reason: "pass", verdict: "pass", verdict_zh: "达标" }, 0);
  assert.equal(it.s.phase, "done");
  it.onEvent({ type: "result_reset", run_id: "r1", reason: "reconnect" }, 1); assert.equal(it.s.phase, "idle");
  it.onEvent({ type: "iterate.stopped", reason: "pass" }, 2); it.onEvent({ type: "result_reset", run_id: "r1", reason: "board_change" }, 3); assert.equal(it.s.phase, "idle");
  it.onEvent({ type: "iterate.stopped", reason: "pass" }, 4); it.onEvent({ type: "iterate.started", limits: { rounds: 5, time_s: 60 } }, 5); assert.equal(it.s.phase, "running");
  assert.ok(IM.sameBoard({ port: "sim:a" }, "sim:a")); assert.ok(!IM.sameBoard({ port: "sim:a" }, "sim:b")); assert.ok(!IM.sameBoard({}, "sim:a")); assert.ok(!IM.sameBoard({ board: "sim:a" }, null));
  const mainSrc = readFileSync("src/main.ts", "utf8");
  assert.match(mainSrc, /const syncIter = \(\) => \{ IT\.reset\(\)/); assert.match(mainSrc, /onBoardForIter\(\(st as any\)\.port/);
  for (const k of ['"iterate.cleared"', '"app_name"']) assert.ok(!mainSrc.includes(k) && !readFileSync("src/iterui.ts", "utf8").includes(k), k + " 只在 fieldmap");
  console.log("r9p6c #101/#104 ok");
}
