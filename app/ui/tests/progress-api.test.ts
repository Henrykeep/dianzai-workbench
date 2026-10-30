import { resolveFix, ACTIONS, Progress, pageHead } from "../src/progress.ts";
import { errorCard } from "../src/agentwatch.ts";
const has = () => true;
// fix_action 解析：可执行 / 未就绪 / 未登记 / null
if (resolveFix("connect", has)?.kind !== "run") throw "connect";
const fd = resolveFix("fetch_deps", has); if (fd?.kind !== "run" || fd.label !== "安装依赖") throw "fetch_deps";
const st = resolveFix("run_selftest", has); if (st?.kind !== "wait" || st.note !== "等待固件支持") throw "run_selftest 未就绪";
const un = resolveFix("no_such_entry", has); if (un?.kind !== "none" || !un.note) throw "未登记兜底";
if (resolveFix(null, has) !== null) throw "null";
if (resolveFix("doctor", () => false)?.kind !== "none") throw "界面没有元素 → 不给可点按钮";
for (const [id, a] of Object.entries(ACTIONS)) if (a.ready !== false && !a.ui) throw "可执行入口必须有 ui：" + id;
// Agent 错误卡复用同一套解析
const e = errorCard({ code: "x", message: "y", fix_action: "run_selftest", retryable: false }, has);
if (e.other?.kind !== "wait" || e.retry || e.settings) throw "错误卡未就绪";
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
