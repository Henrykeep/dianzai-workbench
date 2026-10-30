import { readFileSync } from "fs";
import { setEntrypoints, parseEntrypoints } from "../src/entry.ts";
setEntrypoints(readFileSync("../../docs/dev/entrypoints.yaml", "utf8")   /* make check 在 app/ui 下跑 */);
import { resolveFix, ACTIONS, Progress, pageHead } from "../src/progress.ts";
import { errorCard } from "../src/agentwatch.ts";
const has = () => true;
// fix_action 解析：可执行 / 未就绪 / 未登记 / null
if (resolveFix("connect", has)?.kind !== "run") throw "connect";
const fd = resolveFix("fetch_deps", has); if (fd?.kind !== "run" || fd.label !== "安装依赖") throw "fetch_deps";
const st = resolveFix("run_selftest", has); if (st?.kind !== "run" || st.label !== "读取自检" || ACTIONS.run_selftest.ui !== "seal-selftest") throw "run_selftest 已就绪 → 封箱页「读取自检」";
if (ACTIONS.params_flash.ui !== "tb-save" || ACTIONS.params_flash.step !== "调参") throw "params_flash → 调参页「保存参数」";
const un = resolveFix("no_such_entry", has); if (un?.kind !== "none" || !un.note) throw "未登记兜底";
if (resolveFix(null, has) !== null) throw "null";
if (resolveFix("doctor", () => false)?.kind !== "none") throw "界面没有元素 → 不给可点按钮";
for (const [id, a] of Object.entries(ACTIONS)) if (!a.ui) throw "可执行入口必须有 ui：" + id;
// 未就绪来自入口表 ready: false，而不是前端写死
const t = parseEntrypoints("  - {id: foo, label: 甲, at: x, ui: y, ready: false, ops: []}\n  - {id: bar, label: 乙, at: x, ui: z, ops: []}");
if (t.get("foo")?.ready !== false || t.get("bar")?.ready !== true || t.get("foo")?.label !== "甲") throw "parseEntrypoints";
setEntrypoints("  - {id: run_selftest, label: 板上自检, at: x, ui: y, ready: false, ops: []}");
if (resolveFix("run_selftest", has)?.kind !== "wait") throw "入口表标 ready: false 时置灰（不看 ACTIONS）";
setEntrypoints(readFileSync("../../docs/dev/entrypoints.yaml", "utf8"));
if (/\{id:[^}]*ready: false/.test(readFileSync("../../docs/dev/entrypoints.yaml", "utf8"))) throw "入口表不应再有未就绪行";
// Agent 错误卡复用同一套解析
const e = errorCard({ code: "x", message: "y", fix_action: "run_selftest", retryable: false }, has);
if (e.other?.kind !== "run" || e.otherId !== "run_selftest" || e.retry || e.settings) throw "错误卡修复入口";
// Agent human_only（gateway.HUMAN_ONLY）：写「需在封箱页由人确认」，只给跳转封箱页（jump，不替人点）
const ho = errorCard({ code: "human_only", message: "切换运行模式只能由人完成", fix: "请到封箱页确认", fix_action: "precontest", retryable: false } as any, has);
if (ho.title !== "需在封箱页由人确认" || ho.otherId !== "set_run_mode" || ho.other?.label !== "前往封箱" || !ACTIONS.set_run_mode.jump || ho.retry) throw "human_only 卡";
const e2 = errorCard({ code: "x", message: "y", fix_action: "bogus", retryable: false }, has);
if (e2.other?.kind !== "none") throw "错误卡未登记";
// mock progress.get（progress 分支 8f1cad7 形状）：blocks 指到的步骤
const p: Progress = {
  steps: [{ id: "req", title: "读题", state: "doing" }, { id: "project", title: "工程", state: "blocked" }, { id: "sim", title: "仿真", state: "blocked" }] as any,
  current: "req", next: { title: "工程", action: "project_flow", hint: "" },
  blockers: [{ code: "missing_deps", message: "开发环境缺少必需依赖：arm-none-eabi-gcc。", fix_action: "fetch_deps", blocks: ["project", "sim"] }], mode: "tethered",
};
const blockedSteps = p.steps.filter(s => p.blockers.some(b => b.blocks?.includes(s.id))).map(s => s.id);
if (blockedSteps.join() !== "project,sim") throw "blocks 映射";
const p2 = { ...p, next: { title: "运行自检，按提示安装缺失依赖", action: "doctor", hint: "" } };
const hd = pageHead(p2 as Progress); if (hd.action !== "doctor" || hd.label !== "运行自检") throw "阻塞型 next → 主按钮 " + JSON.stringify(hd);
console.log("progress-api ok");
