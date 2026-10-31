import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { statusWords, linkQuality, reconnectText, filterCmds, loopLine, zoomSel, modeZh } from "../src/r9p6";
import { resultCardHtml, currentMetrics, compareRows, compareRaw, cardView, type Stopped } from "../src/iterui";
import { rangeLabel, fmtP, type Param } from "../src/params";
import { metricCardHtml, VERDICT_LABEL, targetText, sortItems, exportArgs } from "../src/metriccard";
import { toMetricsCard, unitOfKey } from "../src/fieldmap";
import { kindOf } from "../src/timeline";
import { boardName } from "../src/batch1";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

// 1) 换行后第二行不以「·」开头：分隔点挂在前一项末尾（::after），不再用 span+span::before
const css = readFileSync("src/style.css", "utf8");
assert.match(css, /\.life span\+span::before\{content:none!important\}/);
assert.match(css, /\.life span:not\(:last-child\)::after\{content:" · "/);

// 2) 状态位白话
const sw = statusWords({ reset: "#12", hb_flags: ["堵转", "bit20"] });
assert.equal(sw.reset, "未知复位原因（代码 12）");
assert.deepEqual(sw.flags, ["检测到电机堵转", "未知状态位 bit20"]);
assert.equal(statusWords({ reset: "看门狗" }).reset, "看门狗复位（程序卡死过）");
assert.deepEqual(statusWords({}), { reset: "", flags: [] });

// 3) 链路质量：只用已有字段，缺就「—」
assert.equal(linkQuality([]).text, "链路 —");
const cell = (fps: number, crc = 0, drops = 0) => ({ i: 0, dt: 1, fps, crc, drops, bytes: 0, log_t: null, plot_t: null });
assert.match(linkQuality([cell(100), cell(100)]).text, /良好 · 100 帧\/s · 丢包 0\.0%/);
assert.equal(linkQuality([cell(90, 5, 5)]).tone, "bad");
assert.match(linkQuality([{ ...cell(50), crc: undefined as any }]).text, /丢包 —/);

// 4) 缩放选区
assert.deepEqual(zoomSel(3, 1), [1, 3]); assert.equal(zoomSel(1, 1), null); assert.equal(zoomSel(NaN, 1), null);

// 5) 事件竖线：迭代开始等有中文短名，未知 kind 原样
assert.equal(kindOf("iter_start")[0], "迭代开始"); assert.equal(kindOf("estop")[0], "急停"); assert.equal(kindOf("zz")[0], "zz");

// 6) 重连细节
assert.equal(reconnectText(0, 3, 10_400, 10_000), "已断开 10 s · 已自动重连 3 次 · 下一次 0.4 s 后");
assert.equal(reconnectText(null, 0, null, 0), "");

// 7) 命令面板
const cmds = [{ id: "go:调参", title: "打开 调参" }, { id: "send", title: "下发参数" }, { id: "estop", title: "急停", hint: "危险" }];
assert.deepEqual(filterCmds(cmds, "调参").map(c => c.id), ["go:调参"]);
assert.equal(filterCmds(cmds, "").length, 3); assert.equal(filterCmds(cmds, "不存在").length, 0);

// 8) 通用化：非小球项目（三层环 / rpm 速度环）
assert.equal(loopLine({ loops: [{ name: "电流环", level: 1 }, { name: "速度环", level: 2, locked: ["cur_kp"] }, { name: "位置环", level: 3 }] }, "速度环"), "第 2/3 层 · 速度环 · 已锁定：cur_kp");
assert.equal(loopLine({ loops: [{ name: "温度" }] }), "共 1 层"); assert.equal(loopLine({}), "");
assert.equal(modeZh("speed"), "速度环"); assert.equal(modeZh("torque_x"), "torque_x");   // 未知模式不再默认「位置环」
assert.equal(boardName("sim:fan_rpm"), "仿真 · 仿真板");
assert.equal(unitOfKey("speed_rpm"), "rpm");
const rpmRows = compareRows({ overshoot_pct: 20, ripple_rpm: 30 }, { overshoot_pct: 5, ripple_rpm: 12 });
assert.deepEqual(rpmRows.map(r => r[0]), ["超调", "ripple_rpm"]); assert.match(rpmRows[1][2], /12 rpm/);

// 9) 不可行情形：结论只能是未达标 / 未判定，原因白话写在标题下
for (const [reason, re] of [["saturation", /饱和/], ["delay_too_large", /延迟太大/], ["unstable_zero", /不稳定零点/]] as const) {
  for (const v of ["fail", "unknown"] as const) {
    const r: Stopped = { reason, best: { iter: 4, params: { kp: 1 } }, verdict: { v, zh: v === "fail" ? "未达标" : "未判定" } } as any;
    const h = resultCardHtml(r, esc, { canApply: true, applyReady: true });
    assert.match(h, /class="rc-why"/); assert.match(h, re);
    assert.ok(!/it-verdict pass/.test(h) && !/>达标</.test(h), "不可行不能长得像达标");
  }
}
assert.match(cardView({ reason: "weird_code", best: null } as any).reason, /其他（weird_code）/);

// 10) 通用指标卡：控制 / 测量 / 电源
const mc = (kind: string, items: any[]) => ({ metrics_card: { task_kind: kind, items } });
const meas = mc("measure", [
  { name: "频率", clause: "要求(3)", spec_text: "频率测量误差不大于 0.1%", target: { cmp: "<=", threshold: 0.1, unit: "%" }, measured: { value: 0.04, unit: "%", method: "等精度测频", n: 10 }, uncertainty: 0.01, verdict: "pass", verdict_zh: "达标", pass_basis: "10 次最大误差", source: "calibrated", evidence: "logs/f.dzlog" },
  { name: "相位差", clause: "要求(1)", spec_text: "相位差测量误差 ≤ 2°", target: null, measured: { value: 1.3, unit: "°" }, verdict: "unknown", source: "real" },
]);
const mh = metricCardHtml(meas);
assert.match(mh, /指标卡 · 测量类/); assert.match(mh, /要求\(3\)/); assert.match(mh, /0\.04 ± 0\.01 %/); assert.match(mh, /按默认判定/);
assert.match(mh, /缺测量不确定度/); assert.match(mh, /待标定/); assert.match(mh, /data-evidence="logs\/f\.dzlog"/); assert.match(mh, /实机 · 已标定/);
const pw = metricCardHtml(mc("power", [{ name: "纹波", spec_text: "输出纹波 ≤ 50 mVpp", target: { cmp: "<=", threshold: 50, unit: "mVpp" }, measured: { value: 72, unit: "mVpp" }, verdict: "fail", verdict_zh: "不达标", source: "sim" }, { name: "效率", target: { cmp: ">=", threshold: 85, unit: "%" }, measured: { value: 88, unit: "%" }, verdict: "pass" }]));
assert.match(pw, /电源类/); assert.match(pw, /72 mVpp/); assert.match(pw, /仿真标称/); assert.ok(pw.indexOf("纹波") < pw.indexOf("效率"), "不达标排前");
assert.equal(metricCardHtml({}), "");
assert.equal(toMetricsCard(mc("weird", []))!.kind, "other");

// 11) 随机项目夹具：任意环数 / 参数 / 单位 / 指标集 / 缺字段
const seed = +(process.env.DZ_SEED ?? Date.now() % 1e9);
console.log(`r9p6 fuzz seed=${seed}（复现：DZ_SEED=${seed}）`);
let st = seed >>> 0 || 1;
const rnd = () => { st ^= st << 13; st >>>= 0; st ^= st >>> 17; st ^= st << 5; st >>>= 0; return st / 4294967296; };
const pick = <T,>(a: T[]): T => a[Math.floor(rnd() * a.length)];
const maybe = <T,>(v: T): T | undefined => rnd() < 0.25 ? undefined : v;
const UNITS = ["rpm", "%RH", "kPa", "A", "°C", "mVpp", "dB", "Hz", "°", "%", "s", "ms", "zz单位", "N·m", ""];
const PARAMS = ["kp", "ki", "kd", "ff_gain", "out_limit", "温度前馈系数（加热段）", "i_max", "speed_kp", "dead_band", "滤波截止频率与采样周期之比"];
const METS = { control: ["overshoot_pct", "settle_ms", "ss_err_pct", "rise_ms", "iae"], measure: ["freq_err_pct", "phase_err_deg", "thd_pct"], power: ["ripple_mvpp", "efficiency_pct", "load_reg_pct"] } as const;
const BAD = /undefined|NaN|\[object|2026H|小球|球环|motor_pos/;
for (let k = 0; k < 60; k++) {
  const kind = pick(["control", "measure", "power", "other"] as const);
  const nl = 1 + Math.floor(rnd() * 3), loops = Array.from({ length: nl }, (_, i) => ({ name: maybe(`环${i + 1}`), level: maybe(i + 1) }));
  const ps: Param[] = Array.from({ length: 1 + Math.floor(rnd() * 5) }, () => ({ name: pick(PARAMS), type: pick(["f32", "i32"]), min: 0, max: rnd() * 100, unit: maybe(pick(UNITS)), default: 0 }));
  const period = maybe(+(rnd() * 0.05).toFixed(4));
  const ms = kind === "other" ? [...METS.control] : [...METS[kind === "measure" || kind === "power" ? kind : "control"]];
  const metrics = Object.fromEntries(ms.filter(() => rnd() < 0.7).map(m => [m, rnd() < 0.1 ? NaN : rnd() * 50]));
  const best = Object.fromEntries(Object.entries(metrics).map(([m, v]) => [m, rnd() < 0.2 ? undefined : (v as number) * rnd()]));
  const verdict = maybe({ v: pick(["pass", "fail", "unknown"] as const), zh: pick(["", "未达标", "未判定", "达标"]) });
  const r: Stopped = { reason: pick(["saturation", "budget_rounds", "pass", "x_unknown", ""]), message_zh: maybe("说明"),
    best: rnd() < 0.15 ? null : { iter: Math.floor(rnd() * 9), params: Object.fromEntries(ps.map(p => [p.name, rnd() < 0.1 ? NaN : rnd() * 10])), metrics: best },
    base: rnd() < 0.3 ? null : metrics as any, verdict } as any;
  const items = Array.from({ length: Math.floor(rnd() * 5) }, () => {
    const unit = pick(UNITS);
    return { name: maybe(pick(["频率", "相位差", "失真度", "纹波", "效率", "负载调整率", "转速", "湿度"])), clause: maybe(`要求(${1 + Math.floor(rnd() * 6)})`), spec_text: maybe("题目原文"),
      target: rnd() < 0.3 ? null : { cmp: pick(["<=", ">=", "abs_le", "?"]), threshold: maybe(rnd() * 100), unit },
      measured: maybe({ value: maybe(rnd() < 0.1 ? NaN : rnd() * 100), unit, method: maybe("方法"), n: maybe(5) }),
      uncertainty: maybe(rnd()), verdict: maybe(pick(["pass", "fail", "unknown", "bogus"])), verdict_zh: maybe("x"), source: maybe(pick(["sim", "real", "calibrated", "?"])), evidence: maybe("a.dzlog"),
      tuning: rnd() < 0.2 ? { best: { iter: 2, params: { kp: 1.5 } } } : undefined, calibration: rnd() < 0.2 ? { coeffs: [1, NaN, 2], signal_source: maybe("信号源") } : undefined };
  });
  const card = { metrics_card: { task_kind: kind, items } };
  const loopsT = loopLine({ loops });
  const out = [resultCardHtml(r, esc, { canApply: true, applyReady: rnd() < 0.5 }), currentMetrics(r), ...compareRows(r.base, r.best?.metrics).flat(), metricCardHtml(card), loopsT,
    ...ps.map(p => `${p.name} ${rangeLabel(p, rnd() < 0.5, rnd() < 0.2 ? undefined : 1)} ${fmtP(rnd() < 0.2 ? undefined : 3, p)}`), period == null ? "采样周期 —" : `采样周期 ${period} s`].join("\n");
  assert.ok(!BAD.test(out), `seed=${seed} #${k}: ${out.match(BAD)?.[0]}\n${out.slice(0, 400)}`);
  // 缺值一律「—」；未知单位原样显示
  for (const it of toMetricsCard(card)!.items) {
    if (!it.measured || it.measured.value == null) assert.ok(metricCardHtml(card).includes("—"), `seed=${seed} 缺实测值要显示 —`);
    else if (it.measured.unit) assert.ok(metricCardHtml(card).includes(esc(it.measured.unit)), `seed=${seed} 单位 ${it.measured.unit} 被丢了`);
    assert.ok(Object.values(VERDICT_LABEL).includes(VERDICT_LABEL[it.verdict]));
    if (!it.target || it.target.thr == null) assert.equal(targetText(it), "按默认判定");
  }
  if (!r.best && !r.base) assert.match(currentMetrics(r), /—/);
  // 结论只来自 verdict：没给或不是 pass → 标题绝不是 pass 样式
  if (r.verdict?.v !== "pass") assert.ok(!/it-verdict pass/.test(out), `seed=${seed} 假达标`);
  sortItems(toMetricsCard(card)!);
}
// 未知单位在比较行里原样显示
assert.match(compareRaw({ round0: [{ key: "hum", value: 60, unit: "%RH" }], best: [{ key: "hum", value: 55, unit: "%RH" }], unchanged: false, note: "" })[0][2], /55 %RH/);
console.log("r9p6 ok");
// 12) 后端定稿字段：method / manual_steps / procedure / manual_entry / source=manual / 来源未知；导出走后端 op
{

  const h = metricCardHtml({ metrics_card: { task_kind: "power", items: [{ name: "效率", method: "manual", manual_steps: ["接电子负载", "读功率计"], procedure: ["满载 5 min 后读数"], manual_entry: { value: 86.2, by: "队员A", at: "2026-10-31 19:20" }, measured: { value: 86.2, unit: "%" }, source: "manual", verdict: "pass" },
    { name: "纹波", source: "sim", source_note: "来源未知", measured: { value: 40, unit: "mVpp" }, verdict: "unknown" }] } });
  assert.match(h, /人工测量/); assert.match(h, /人工测量步骤（2 步）/); assert.match(h, /评审测试步骤（1 步）/); assert.match(h, /人工录入 86\.2 % · 队员A · 2026-10-31 19:20/);
  assert.match(h, /仿真标称 · 来源未知/); assert.match(h, /data-mc-export="csv"/);
  assert.deepEqual(exportArgs("xlsx"), { op: "metrics_export", args: { format: "xlsx" } });
  const all = readFileSync("src/metriccard.ts", "utf8") + readFileSync("src/main.ts", "utf8");
  assert.ok(!/text\/csv|\.csv"|Blob\(/.test(all), "前端不自己生成 CSV");
}
console.log("r9p6 export ok");

// ---- r9p6b：#90 #91 #95 ----
import { stripToolMarkup } from "../src/sanitize";
import { errParts } from "../src/errors";
import { errFixAction } from "../src/fieldmap";
{
  const eq = (a: unknown, b: unknown, m: string) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${m}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`); };
  eq(stripToolMarkup('好的<tool_call>{"name":"x"}</tool_call>已完成'), "好的已完成", "tool_call pair");
  eq(stripToolMarkup("A<|tool_calls_section_begin|>x<|tool_calls_section_end|>B"), "AB", "kimi tokens");
  eq(stripToolMarkup('先读文件\n<function=read>{"p":1}</function>'), "先读文件", "function=");
  eq(stripToolMarkup("答案<|im_end|>"), "答案", "stray token");
  eq(stripToolMarkup("流式中<tool_call>{\"na"), "流式中", "unterminated during streaming");
  eq(stripToolMarkup("[TOOL_CALLS][{}]\n结果 1<2 且 a|b"), "结果 1<2 且 a|b", "TOOL_CALLS line");
  for (const keep of ["kp 从 0.5 改成 0.8", "a < b > c", "用 `make check` 检查", "```c\nint x;\n```", "<b>不是标记</b>"]) eq(stripToolMarkup(keep), keep, "keeps " + keep);
  eq(errParts({ code: "x", message: "busy", message_zh: "正在自动迭代" }).what, "正在自动迭代", "message_zh");
  eq(errParts({ code: "x", message: "busy" }).why, "后端未给原因", "no reason");
  eq(errParts({ code: "x", message: "busy", reason_zh: "迭代没停" } as any).why, "迭代没停", "reason_zh");
  eq(errFixAction({ fix_action: "stop_iteration" }), "stop_iteration", "fix_action");
  eq(errFixAction({ l: "stop_iteration" }), "stop_iteration", "l");
  eq(errFixAction({}), "", "none");
  const html = require("fs").readFileSync("index.html", "utf8");
  if (/car_2wd/.test(html)) throw new Error("car_2wd placeholder");
  console.log("r9p6b ok");
}
// #76 参数数字 ≥16px：每一档 --t-lg ≥16，且 .prow .in.num 有一条不在任何 @media 里的 var(--t-lg) 规则
{
  const css: string = require("fs").readFileSync("src/style.css", "utf8");
  for (const m of css.matchAll(/--t-lg:\s*(\d+)px/g)) if (+m[1] < 16) throw new Error("--t-lg < 16: " + m[0]);
  let depth = 0, ok = false, buf = "";
  for (const ch of css) { if (ch === "{") { if (depth === 0 && /\.prow \.in\.num/.test(buf) && !/@media/.test(buf)) ok = true; depth++; buf = ""; } else if (ch === "}") { depth--; buf = ""; } else if (depth === 0) buf += ch; }
  const tail = css.slice(css.lastIndexOf("#76 参数数字在所有宽度"));
  if (!ok || !/\.prow \.in\.num[^{]*\{font-size:var\(--t-lg\)\}/.test(tail)) throw new Error("param num 16px rule missing");
  for (const m of css.matchAll(/\.prow \.in\.num\{[^}]*font:\s*(\d+)px/g)) if (+m[1] < 16) throw new Error("prow num " + m[1]);
  console.log("r9p6b font ok");
}
// #88 提交确认卡
import { toCommitReq, commitCardHtml } from "../src/commitcard";
{
  const e = (s: string) => s.replace(/</g, "&lt;");
  const h = commitCardHtml(toCommitReq({ files: [{ path: "src/a.c", status: "M" }, "b.yaml"], commit_message: "调参：kp 0.5→0.8" }), e);
  for (const t of ["src/a.c", "b.yaml", "修改", "调参：kp 0.5→0.8", "确认提交", "取消", "2 个文件"]) if (!h.includes(t)) throw new Error("commit card " + t);
  const z = commitCardHtml(toCommitReq({}), e);
  if (!z.includes("disabled") || !z.includes("后端没有给提交说明")) throw new Error("empty commit card");
  if (!require("fs").readFileSync("src/projflow.ts", "utf8").includes("只授权写入文件，不会提交")) throw new Error("write card note");
  console.log("r9p6b commit ok");
}
