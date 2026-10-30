// 项目进度适配层：结构与后端草案 progress.get 一致。接口没上线前，用前端现有数据推断同样的结构；
// 上线后 fetchProgress() 优先用接口结果，界面代码不用改。步骤状态的判断只写在这里。
import { STEPS, Step, STEP_HINT } from "./steps";

export type State = "todo" | "doing" | "done" | "blocked";
export type BlockerCode = "no_board" | "missing_deps" | "gains_zero" | "estop" | "selftest_fail" | "params_not_saved";
// 7 步旅程：id 与后端 progress.get 的 steps[].id 一致；page = 进入时打开的内部页
export const JOURNEY = [
  { id: "req", title: "读题定方案", pages: ["项目"] }, { id: "project", title: "建工程", pages: ["烧录"] },
  { id: "sim", title: "仿真", pages: ["联调"] }, { id: "bringup", title: "上板联调", pages: ["模块", "标定"] },
  { id: "tune", title: "调参", pages: ["调参"] }, { id: "score", title: "评分", pages: ["评分"] }, { id: "seal", title: "封箱", pages: ["封箱"] },
] as const;
export type StepId = typeof JOURNEY[number]["id"];
export interface Blocker { code: BlockerCode; message: string; fix_action: string }
export interface Progress {
  steps: { id: StepId; title: string; state: State; reason?: string; detail?: string }[];
  current: StepId;
  next: { title: string; action: string; hint: string } | null;
  blockers: Blocker[];
}
// fix_action / next.action 都是 entrypoints.yaml 的动作 id；这里只记“去哪一步、点哪个已有元素”，不新增入口
export const ACTIONS: Record<string, { step?: Step; ui: string }> = {
  connect: { ui: "connect" }, estop_clear: { ui: "cmd-r" }, doctor: { ui: "doctor" },
  project_flow: { step: "项目", ui: "pflow" }, flash: { step: "烧录", ui: "fw-flash" },
  tune_relay: { step: "调参", ui: "ag-relay" }, params: { step: "调参", ui: "p-send" },
  params_flash: { step: "封箱", ui: "pre-save" }, score: { step: "评分", ui: "score" }, precontest: { step: "封箱", ui: "pre" },
};
// 每步“主动作”：下一步提示里的那个按钮跳到哪
const MAIN: Record<Step, string> = { 项目: "project_flow", 烧录: "flash", 模块: "connect", 联调: "connect", 标定: "connect", 调参: "params", 评分: "score", 封箱: "precontest" };

export interface Ctx { current: Step; connected: boolean; estop: boolean; gainsZero: boolean; paramsDirty: boolean; selftestFail: boolean; visited: Set<Step> }

export function infer(c: Ctx): Progress {
  const blockers: Blocker[] = [];
  if (!c.connected) blockers.push({ code: "no_board", message: "未连接：尚未连接目标板（可选仿真）", fix_action: "connect" });
  if (c.estop) blockers.push({ code: "estop", message: "已急停：急停已锁定", fix_action: "estop_clear" });
  if (c.selftestFail) blockers.push({ code: "selftest_fail", message: "自检未通过", fix_action: "doctor" });
  if (c.connected && c.gainsZero) blockers.push({ code: "gains_zero", message: "增益为 0：控制器无输出", fix_action: "tune_relay" });
  if (c.paramsDirty) blockers.push({ code: "params_not_saved", message: "参数未下发", fix_action: "params" });
  const pid = (pg: Step) => JOURNEY.find(j => (j.pages as readonly string[]).includes(pg))!.id;
  const seen = new Set([...c.visited].map(pid));
  const curId = pid(c.current), curI = JOURNEY.findIndex(j => j.id === curId);
  const lastSeen = Math.max(...JOURNEY.map((j, i) => (seen.has(j.id) ? i : 0)));
  const steps = JOURNEY.map((j, i) => {
    let state: State = seen.has(j.id) ? (i < lastSeen ? "done" : "doing") : "todo";
    let reason: string | undefined;
    if (j.id === curId && state === "todo") state = "doing";
    if (i >= 2 && j.id !== "sim" && j.id === curId && !c.connected) { state = "blocked"; reason = "未连接"; }
    if (j.id === "score" && c.paramsDirty && state !== "done") { state = "blocked"; reason = "参数未下发"; }
    return { id: j.id, title: j.title, state, reason, detail: STEP_HINT[j.pages[0] as Step] };
  });
  const cur = steps[curI];
  const nx = cur.state !== "done" ? cur : steps.find(s => s.state !== "done");
  const nj = nx && JOURNEY.find(j => j.id === nx.id)!;
  const next = nx && nj ? { title: nx.title, action: MAIN[nj.pages[0] as Step], hint: STEP_HINT[nj.pages[0] as Step] } : null;
  return { steps, current: curId, next, blockers };
}

let noApiUntil = 0;
// 接口优先，失败或没有就推断
export async function fetchProgress(call: (op: string) => Promise<any>, c: Ctx): Promise<Progress> {
  if (Date.now() > noApiUntil) {
    try { const p = await call("progress.get"); if (p && Array.isArray(p.steps)) return p as Progress; } catch { /* 接口还没上线 */ }
    noApiUntil = Date.now() + 30000;   // 没有接口时 30 s 再试一次，避免刷侧车日志
  }
  return infer(c);
}

const LABEL: Record<State, string> = { todo: "未开始", doing: "进行中", done: "已完成", blocked: "已阻塞" };
// 画到左侧导航：每步状态 + 下一步一句话 + 每个 blocker 一个“去解决”（点的是已有入口）
export function render(p: Progress, go: (s: Step) => void) {
  document.querySelectorAll<HTMLElement>("#steps [data-step]").forEach(b => {
    const s = p.steps.find(x => x.id === b.dataset.pid); if (!s) return;
    if (b.classList.contains("sub")) return;   // 子项（标定）跟随父步，不单独标状态
    b.dataset.state = s.state;
    b.classList.toggle("done", s.state === "done");
    b.classList.toggle("next", p.next?.title === s.title && s.id !== p.current);
    b.title = `${s.title} · ${LABEL[s.state]}${s.reason ? "：" + s.reason : ""}\n${s.detail ?? ""}`;
  });
  const h = document.getElementById("step-hint"); if (!h) return;
  const run = (a: string) => { const t = ACTIONS[a]; if (!t) return; if (t.step) go(t.step); setTimeout(() => document.getElementById(t.ui)?.click(), 0); };
  h.replaceChildren();
  if (p.next) { const n = document.createElement("span"); n.className = "nx"; n.textContent = `下一步：${p.next.title} — ${p.next.hint}`; h.append(n); }
  for (const b of p.blockers) {
    const a = document.createElement("a"); a.className = "blk"; a.href = "#"; a.dataset.code = b.code;
    a.textContent = `${b.message} · 处理`; a.onclick = e => { e.preventDefault(); run(b.fix_action); };
    h.append(a);
  }
}
