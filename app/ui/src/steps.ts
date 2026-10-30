// 时间线步骤栏（LOGIC_AUDIT §3.1）：项目 → 烧录 → 模块 → 联调 → 标定 → 调参 → 评分 → 封箱。
// 每步一页；顶栏常驻 急停 / 连接 / 排障 / 工具箱。入口登记在 docs/dev/entrypoints.yaml。
// 导航形态参考 MICU templates/auto-embedded/workflow.md（每页声明当前阶段）与 PID_Helper App.tsx（单面板流程）。
export const STEPS = ["项目", "烧录", "模块", "联调", "标定", "调参", "评分", "封箱"] as const;
export type Step = typeof STEPS[number];
export const STEP_HINT: Record<Step, string> = {
  项目: "读题 → 选型 → 导入工程 → 资源分配 → 生成（每步确认才写）",
  烧录: "编译 → 烧录 → 心跳核对；选调试探针",
  模块: "单模块收发：原始字节、常用指令、板端命令、ELF 变量",
  联调: "示波 / 频谱 / 事件时间线，看子系统一起跑",
  标定: "极性、传感器、零偏等标定值",
  调参: "左曲线右参数；底部实验 → 判定 → 回到…；右栏 Agent 助手",
  评分: "按评分项跑 N 轮、判到位、存证据",
  封箱: "赛前全绿检查、存 flash、回读、写回 yaml",
};
// 页面布局：哪些区域可见（dock = 参数栏，side = 右栏，scope = 曲线区）、进页时右栏 / 曲线区切到哪个标签
type Lay = { dock: boolean; side: boolean; scope: boolean; sideTab?: string; view?: string; dockTab?: string };
export const LAYOUT: Record<Step, Lay> = {
  项目: { dock: false, side: false, scope: false },
  烧录: { dock: false, side: false, scope: false },
  模块: { dock: true, side: true, scope: true, view: "raw", dockTab: "board", sideTab: "chans" },
  联调: { dock: false, side: true, scope: true, view: "plot", sideTab: "chans" },
  标定: { dock: false, side: false, scope: false },
  调参: { dock: true, side: true, scope: true, view: "plot", dockTab: "params", sideTab: "agent" },
  评分: { dock: false, side: true, scope: true, view: "plot", sideTab: "score" },
  封箱: { dock: false, side: false, scope: false },
};
export const nextOf = (s: Step): Step | null => STEPS[STEPS.indexOf(s) + 1] ?? null;
export function hintText(s: Step, connected: boolean): string {
  const n = nextOf(s);
  const need = !connected && LAYOUT[s].scope ? "（先在左上角连接板子）" : "";
  return `当前：${s} — ${STEP_HINT[s]}${need}${n ? ` · 下一步：${n}` : " · 最后一步"}`;
}

const KEY = "dz.step";
export function initSteps(connected: () => boolean): (s: Step) => void {
  const app = document.querySelector<HTMLElement>(".app")!;
  const bar = document.getElementById("steps")!;
  const click = (sel: string) => document.querySelector<HTMLElement>(sel)?.click();
  const go = (s: Step) => {
    const L = LAYOUT[s];
    app.dataset.step = s;
    app.classList.toggle("full", !L.dock && !L.side);
    app.classList.toggle("nodock", !L.dock);
    bar.querySelectorAll<HTMLElement>("[data-step]").forEach(b => {
      b.classList.toggle("on", b.dataset.step === s);
      b.classList.toggle("next", b.dataset.step === nextOf(s));
    });
    document.querySelectorAll<HTMLElement>(".work > [data-page]").forEach(p => (p.hidden = p.dataset.page !== s));
    document.querySelector<HTMLElement>(".work > .scope")!.hidden = !L.scope;
    if (L.view) click(`#view [data-v="${L.view}"]`);
    if (L.dockTab) click(`#dock-tabs [data-d="${L.dockTab}"]`);
    if (L.sideTab) click(`#rail [data-side="${L.sideTab}"]`);
    localStorage.setItem(KEY, s);
    hint();
  };
  const hint = () => { const s = (app.dataset.step || "项目") as Step; document.getElementById("step-hint")!.textContent = hintText(s, connected()); };
  bar.querySelectorAll<HTMLElement>("[data-step]").forEach(b => (b.onclick = () => go(b.dataset.step as Step)));
  setInterval(hint, 1000);
  const saved = localStorage.getItem(KEY) as Step | null;
  go(saved && STEPS.includes(saved) ? saved : "项目");
  return go;
}
