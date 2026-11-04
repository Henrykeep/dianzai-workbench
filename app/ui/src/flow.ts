// 首页流程总览：8 步来自 stages.ts（与工具箱分组同一张表）。纯函数出模型，DOM 只渲染。
import { STAGES } from "./stages";
export type FlowState = "done" | "cur" | "todo" | "blocked";
export interface FlowFacts { hasProject: boolean; connected: boolean; tuned: boolean; scored?: boolean }
export interface FlowItem { id: string; n: number; title: string; hint: string; action: string; page: string; state: FlowState; reason?: string; fix?: "connect" }
const NEEDS_BOARD = new Set(["flash", "debug", "tune"]);
export function flowModel(f: FlowFacts): FlowItem[] {
  const done: Record<string, boolean> = {
    req: f.hasProject, plan: f.hasProject, project: f.hasProject,
    wiring: f.hasProject && f.connected, flash: f.hasProject && f.connected,
    debug: f.hasProject && f.connected && f.tuned, tune: f.hasProject && f.connected && f.tuned, report: !!f.scored,
  };
  let cur = STAGES.findIndex(s => !done[s.id]); if (cur < 0) cur = STAGES.length;
  return STAGES.map((s, i) => {
    let state: FlowState = done[s.id] ? "done" : i === cur ? "cur" : "todo";
    const it: FlowItem = { id: s.id, n: i + 1, title: s.title, hint: s.hint, action: s.action, page: s.page, state };
    if (state === "cur" && NEEDS_BOARD.has(s.id) && !f.connected) { it.state = "blocked"; it.reason = "还没连接目标板（也可以先选仿真板）"; it.fix = "connect"; }
    return it;
  });
}
const ZH: Record<FlowState, string> = { done: "已完成", cur: "进行中", todo: "未开始", blocked: "卡住了" };
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
// primary=false：当前步已有页面主按钮时（读需求那步的「新建工程」）只给普通按钮，保证一屏一个主按钮
export function renderFlow(el: HTMLElement, items: FlowItem[], run: (it: FlowItem) => void) {
  el.innerHTML = items.map(it => {
    const open = it.state === "cur" || it.state === "blocked";
    const pri = open && it.id !== "req";
    const btn = it.fix ? `<button type="button" class="btn${pri ? " pri" : ""}" data-flow="${it.id}" data-fix="connect">连接目标板</button>`
      : `<button type="button" class="btn${pri ? " pri" : ""}" data-flow="${it.id}">${esc(it.action)}</button>`;
    return `<li class="fl-i ${it.state}" data-stage="${it.id}"><span class="fl-n">${it.state === "done" ? "✓" : it.n}</span><div class="fl-b"><div class="fl-t"><b>${esc(it.title)}</b><span class="fl-s">${ZH[it.state]}</span></div>${open ? `<p>${esc(it.reason ?? it.hint)}</p><div class="fl-a">${btn}</div>` : ""}</div></li>`;
  }).join("");
  el.onclick = e => { const b = (e.target as HTMLElement).closest<HTMLElement>("[data-flow]"); const it = b && items.find(x => x.id === b.dataset.flow); if (it) run(it); };
}
