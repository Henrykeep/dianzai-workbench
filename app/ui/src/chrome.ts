// 外壳行为：主题切换（记在 localStorage）、弹出菜单点外面 / Esc / 点菜单项后收起。
const KEY = "dz.theme";

export function applyTheme(t: string): void {
  document.documentElement.dataset.theme = t;
  // plot 通过 getComputedStyle 读变量，切主题后让它重绘
  window.dispatchEvent(new Event("dz-theme"));
}

export function initChrome(): void {
  const saved = localStorage.getItem(KEY);
  applyTheme(saved === "light" ? "light" : "dark");
  document.getElementById("theme")?.addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    localStorage.setItem(KEY, t);
    applyTheme(t);
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
