import { createElement, Activity, SlidersHorizontal } from "lucide";
// 外壳行为：主题切换（记在 localStorage）、弹出菜单点外面 / Esc / 点菜单项后收起。
const KEY = "dz.theme";

export function applyTheme(t: string): void {
  document.documentElement.dataset.theme = t;
  // plot 通过 getComputedStyle 读变量，切主题后让它重绘
  window.dispatchEvent(new Event("dz-theme"));
}

// 所有下拉弹层（details.menu > .pop）：打开时按可用空间决定向上 / 向下展开，不跑出窗口
function placePop(d: HTMLDetailsElement): void {
  const pop = d.querySelector<HTMLElement>(":scope > .pop"); if (!pop || !d.open) return;
  pop.classList.remove("pop-up", "pop-down"); pop.style.maxHeight = "";
  const s = d.getBoundingClientRect(), h = pop.scrollHeight, below = innerHeight - s.bottom - 8, above = s.top - 8;
  const up = h > below && above > below;
  pop.classList.add(up ? "pop-up" : "pop-down");
  pop.style.maxHeight = `${Math.max(120, up ? above : below) - 4}px`;
}
document.addEventListener("toggle", e => { const d = e.target as HTMLElement; if (d instanceof HTMLDetailsElement && d.classList.contains("menu")) placePop(d); }, true);
addEventListener("resize", () => document.querySelectorAll<HTMLDetailsElement>("details.menu[open]").forEach(placePop));
export function initChrome(): void {
  const saved = localStorage.getItem(KEY);
  const order = ["dark", "light", "hc"];
  applyTheme(order.includes(saved ?? "") ? saved! : "dark");
  document.getElementById("theme")?.addEventListener("click", () => {
    const t = order[(order.indexOf(document.documentElement.dataset.theme ?? "dark") + 1) % order.length];
    localStorage.setItem(KEY, t);
    applyTheme(t);
  });
  initTabs();
  // 左侧导航可折叠成只显示图标，记在 localStorage
  const fold = (on: boolean) => { document.documentElement.classList.toggle("nav-folded", on); localStorage.setItem("dz.nav", on ? "1" : "0"); };
  fold(localStorage.getItem("dz.nav") === "1");
  document.getElementById("nav-fold")?.addEventListener("click", () => {
    const r = document.documentElement;
    if (matchMedia("(max-width:1500px)").matches) r.classList.toggle("nav-open"); // 窄窗口默认收起，按钮临时展开
    else fold(!r.classList.contains("nav-folded"));
  });
  const menus = () => Array.from(document.querySelectorAll<HTMLDetailsElement>("details.menu[open]"));
  document.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    for (const m of menus()) {
      if (!m.contains(t) || t.closest(".mi")) m.open = false;
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") menus().forEach((m) => (m.open = false));
  });
}

// 动态插入的空状态用的图标（静态 HTML 里的图标由 createIcons 处理）
const ICONS = { activity: Activity, sliders: SlidersHorizontal };
export const icon = (k: keyof typeof ICONS) => createElement(ICONS[k]).outerHTML;
export const emptyState = (k: keyof typeof ICONS, text: string) => `<div class="empty-s">${icon(k)}<span>${text}</span></div>`;

// 停靠区分页（docs/26 P14：一次只开一个面板）。按钮 data-<k>=名字，面板同名 data-<k>；
// rail 切右栏（data-side），dock 标签切底部面板（data-d）。
function bindTabs(btns: NodeListOf<HTMLElement>, panes: NodeListOf<HTMLElement>, key: string): void {
  btns.forEach(b => b.addEventListener("click", () => {
    const v = b.dataset[key];
    btns.forEach(x => x.classList.toggle("on", x === b));
    panes.forEach(p => (p.hidden = p.dataset[key] !== v));
    b.querySelector(".pip")?.setAttribute("hidden", "");
  }));
}
function initTabs(): void {
  bindTabs(document.querySelectorAll("#rail [data-side]"), document.querySelectorAll(".side > .pane"), "side");
  bindTabs(document.querySelectorAll("#dock-tabs [data-d]"), document.querySelectorAll(".dock > .dk"), "d");
}
// 右栏某面板有新内容（如 Agent 提议）但没打开时，rail 图标上亮一个小点
export function notifySide(name: string): void {
  const b = document.querySelector<HTMLElement>(`#rail [data-side="${name}"]`);
  if (b && !b.classList.contains("on")) b.querySelector(".pip")?.removeAttribute("hidden");
}
