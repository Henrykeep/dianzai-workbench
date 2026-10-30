// 项目进度适配层：结构与后端草案 progress.get 一致。接口没上线前，用前端现有数据推断同样的结构；
// 上线后 fetchProgress() 优先用接口结果，界面代码不用改。步骤状态的判断只写在这里。
import { STEPS, Step, STEP_HINT } from "./steps";
import { entry } from "./entry";

export type State = "todo" | "doing" | "done" | "blocked";
export type BlockerCode = "no_board" | "missing_deps" | "gains_zero" | "estop" | "selftest_fail" | "params_not_saved";
// 7 步旅程：id 与后端 progress.get 的 steps[].id 一致；page = 进入时打开的内部页
export const JOURNEY = [
  { id: "req", title: "读题定方案", pages: ["项目"] }, { id: "project", title: "建工程", pages: ["烧录"] },
  { id: "sim", title: "仿真", pages: ["联调"] }, { id: "bringup", title: "上板联调", pages: ["模块", "标定"] },
  { id: "tune", title: "调参", pages: ["调参"] }, { id: "score", title: "评分", pages: ["评分"] }, { id: "seal", title: "封箱", pages: ["封箱"] },
] as const;
export type StepId = typeof JOURNEY[number]["id"];
export interface Blocker { code: BlockerCode; message: string; fix_action: string | null; blocks?: string[] }
export interface Progress {
  steps: { id: StepId; title: string; state: State; reason?: string; detail?: string }[];
  current: StepId;
  next: { title: string; action: string; hint: string } | null;
  blockers: Blocker[];
  mode?: string | null;
}
// fix_action / next.action 都是 entrypoints.yaml 的动作 id；这里只记“去哪一步、点哪个已有元素”，不新增入口
export const ACTIONS: Record<string, { step?: Step; ui: string; label?: string; jump?: boolean }> = {
  // jump = 只跳到那一页并聚焦按钮，不替用户点（切换运行模式必须人确认；Agent 只给跳转）
  project_list: { step: "项目", ui: "pj-open", label: "打开项目" },   // project.open 失败的 fix_action：回空状态重新选
  set_run_mode: { step: "封箱", ui: "seal-mode", label: "前往封箱", jump: true },
  connect: { ui: "connect", label: "连接" }, estop_clear: { ui: "cmd-r", label: "解除并继续" }, doctor: { ui: "doctor", label: "运行自检" },
  blackbox: { ui: "pre-bbtn", label: "读黑匣子" }, llm_cfg: { ui: "ag-cfg", label: "大模型设置" },
  project_flow: { step: "项目", ui: "pflow" }, project_ask: { step: "项目", ui: "pj-ask-go" }, flash: { step: "烧录", ui: "fw-flash" },
  build: { step: "烧录", ui: "fw-build", label: "编译" }, cal_polarity: { step: "标定", ui: "calwiz", label: "极性自检" },
  tune_relay: { step: "调参", ui: "ag-relay", label: "自整定" }, params: { step: "调参", ui: "p-send", label: "下发参数" },
  params_flash: { step: "调参", ui: "tb-save", label: "保存参数" }, run_selftest: { step: "封箱", ui: "seal-selftest", label: "读取自检" }, score: { step: "评分", ui: "score" }, precontest: { step: "封箱", ui: "pre" },
  fetch_deps: { ui: "doctor", label: "安装依赖" },   // missing_deps：自检对话框里按提示安装
};
// fix_action → 按钮：可执行 / 未就绪（置灰「等待固件支持」）/ 未登记（置灰写明原因）。不出现点了没反应的按钮
export type Fix = { kind: "run" | "wait" | "none"; label: string; note?: string };
export function resolveFix(id: string | null | undefined, has: (ui: string) => boolean = ui => !!document.getElementById(ui)): Fix | null {
  if (!id) return null;
  const e = entry(id);   // 入口表 ready: false 优先：登记了但未就绪 → 置灰「等待固件支持」
  if (e && !e.ready) return { kind: "wait", label: ACTIONS[id]?.label ?? e.label, note: "等待固件支持" };
  const t = ACTIONS[id];
  if (!t) return { kind: "none", label: "暂不可用", note: `工作台还没有这个操作的入口（${id}）` };
  const label = t.label ?? ACTION_LABEL[id] ?? "处理";
  if (!t.step && !has(t.ui)) return { kind: "none", label, note: "当前界面没有这个入口" };
  return { kind: "run", label };
}
// 每步“主动作”：下一步提示里的那个按钮跳到哪
const MAIN: Record<Step, string> = { 项目: "project_ask", 烧录: "flash", 模块: "connect", 联调: "connect", 标定: "connect", 调参: "params", 评分: "score", 封箱: "precontest" };

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

// 每页顶部「一句话说明 + 一个主按钮」：说明这一步做什么、做完产出什么；按钮与 progress.next 同源
export const PURPOSE: Record<StepId, string> = {
  req: "把题目或需求整理成需求表与技术方案；产出 requirements.yaml、scheme.yaml。",
  project: "生成或导入工程并编译、烧录到目标板；产出可运行的固件。",
  sim: "在仿真板上跑通控制回路，确认信号与参数结构；产出可用的参数初值。",
  bringup: "逐个模块上板收发并完成标定；产出极性、零偏等标定值。",
  tune: "用阶跃实验与自整定调整参数；产出满足指标的一组参数。",
  score: "按评分项逐项实测并保存证据；产出每项的测试记录与得分。",
  seal: "赛前全绿检查并持久化参数；产出写入 Flash 与 yaml 的定稿参数。",
};
export const ACTION_LABEL: Record<string, string> = {
  project_flow: "开始读需求", project_ask: "新建工程", flash: "烧录固件", connect: "连接目标板", params: "下发参数",
  score: "开始评分", precontest: "开始检查", tune_relay: "自整定", estop_clear: "解除并继续", doctor: "运行自检",
};
export function pageHead(p: Progress): { text: string; label: string; action?: string; goto?: StepId } {
  const cur = p.steps.find(s => s.id === p.current)!;
  const text = PURPOSE[cur.id];
  if (p.next && p.next.title === cur.title) return { text, label: ACTION_LABEL[p.next.action] ?? "开始", action: p.next.action };
  const nx = p.next && p.steps.find(s => s.title === p.next!.title);
  if (nx) return { text, label: `前往${nx.title}`, goto: nx.id };
  // 接口的 next 也可能是“先解决阻塞”（title 不是步骤名，如「运行自检…」）：按钮直接给这个动作
  if (p.next?.action) { const f = resolveFix(p.next.action, () => true); if (f?.kind === "run") return { text, label: f.label, action: p.next.action }; }
  return { text, label: "已完成" };
}
const LABEL: Record<State, string> = { todo: "未开始", doing: "进行中", done: "已完成", blocked: "已阻塞" };
export function runAction(a: string, go: (s: Step) => void) {
  const t = ACTIONS[a]; if (!t || entry(a)?.ready === false || !t.ui) return; if (t.step) go(t.step); setTimeout(() => { const el = document.getElementById(t.ui); if (t.jump) el?.focus(); else el?.click(); }, 0);
}
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
  // 每个 blocker 标到它 blocks 列出的那几步导航下：卡住原因 + fix_action 按钮（接口数据才有 blocks；推断数据不标）
  document.querySelectorAll("#steps .nav-blk").forEach(e => e.remove());
  for (const s of p.steps) {
    const bs = p.blockers.filter(b => b.blocks?.includes(s.id)); if (!bs.length) continue;
    const nav = document.querySelector<HTMLElement>(`#steps [data-pid="${s.id}"]:not(.sub)`); if (!nav) continue;
    nav.dataset.blocked = "1";
    const box = document.createElement("div"); box.className = "nav-blk";
    for (const b of bs) box.append(blockerRow(b, go));
    nav.after(box);
  }
  document.querySelectorAll<HTMLElement>("#steps [data-blocked]").forEach(n => { if (!(n.nextElementSibling as HTMLElement | null)?.classList.contains("nav-blk")) delete n.dataset.blocked; });
  const ph = document.getElementById("pg-head");
  if (ph) {
    const hd = pageHead(p);
    const extra = document.getElementById("pg-tune");   // 调参页「保存参数」常驻在页头，重画时保留
    ph.innerHTML = `<p class="pg-t"></p><button class="btn pri" type="button"></button>`;
    if (extra) ph.querySelector("p")!.after(extra);
    ph.querySelector("p")!.textContent = hd.text;
    const b = ph.querySelector<HTMLButtonElement>(":scope > button.pri")!   /* 不能取第一个 button：调参页常驻的「保存参数」也在页头 */; b.textContent = hd.label; b.disabled = !hd.action && !hd.goto;
    b.onclick = () => { if (hd.action) runAction(hd.action, go); else if (hd.goto) go(JOURNEY.find(j => j.id === hd.goto)!.pages[0] as Step); };
  }
  const h = document.getElementById("step-hint"); if (!h) return;
  const run = (a: string) => runAction(a, go);
  h.replaceChildren();
  if (p.next) { const n = document.createElement("span"); n.className = "nx"; n.textContent = `下一步：${p.next.title} — ${p.next.hint}`; h.append(n); }
  for (const b of p.blockers) {
    const f = resolveFix(b.fix_action);
    if (f?.kind === "run") {
      const a = document.createElement("a"); a.className = "blk"; a.href = "#"; a.dataset.code = b.code;
      a.textContent = `${b.message} · ${f.label}`; a.onclick = e => { e.preventDefault(); run(b.fix_action!); };
      h.append(a);
    } else {   // 未就绪 / 未登记 / 无 fix_action：只写原因，不给可点的链接
      const n = document.createElement("span"); n.className = "blk off"; n.dataset.code = b.code;
      n.textContent = b.message + (f?.note ? ` · ${f.note}` : ""); h.append(n);
    }
  }
}

export function blockerRow(b: Blocker, go: (s: Step) => void): HTMLElement {
  const r = document.createElement("div"); r.className = "nb"; r.dataset.code = b.code;
  const t = document.createElement("span"); t.textContent = b.message; r.append(t);
  const f = resolveFix(b.fix_action);
  if (f) {
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "btn sm"; btn.textContent = f.label;
    if (f.kind === "run") btn.onclick = () => runAction(b.fix_action!, go);
    else { btn.disabled = true; btn.title = f.note ?? ""; const n = document.createElement("span"); n.className = "nb-note"; n.textContent = f.note ?? ""; r.append(btn, n); return r; }
    r.append(btn);
  }
  return r;
}
