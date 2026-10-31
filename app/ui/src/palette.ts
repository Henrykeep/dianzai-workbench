// r9p6 Ctrl+K 命令面板：页面跳转 + 主要动作；↑↓ 选择，Enter 执行，Esc 关闭（Esc 在面板里不触发急停）
import { filterCmds, type Cmd } from "./r9p6";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
export function initPalette(list: () => Cmd[], run: (id: string) => void) {
  const dlg = document.createElement("dialog");
  dlg.className = "pal"; dlg.id = "pal";
  dlg.innerHTML = `<input class="in pal-q" id="pal-q" placeholder="输入页面或动作，如 调参、下发、快照" aria-label="命令"><ul class="pal-l" id="pal-l" role="listbox"></ul><p class="pal-f">↑↓ 选择 · Enter 执行 · Esc 关闭</p>`;
  document.body.append(dlg);
  const q = dlg.querySelector<HTMLInputElement>("#pal-q")!, ul = dlg.querySelector<HTMLElement>("#pal-l")!;
  let sel = 0, cur: Cmd[] = [];
  const render = () => {
    cur = filterCmds(list(), q.value); sel = Math.min(sel, Math.max(0, cur.length - 1));
    ul.innerHTML = cur.length ? cur.map((c, i) => `<li role="option" data-id="${esc(c.id)}" class="${i === sel ? "on" : ""}${c.hint === "危险" ? " crit-t" : ""}"><span>${esc(c.title)}</span>${c.keys ? `<kbd>${esc(c.keys)}</kbd>` : c.hint ? `<i>${esc(c.hint)}</i>` : ""}</li>`).join("") : `<li class="none">没有匹配的命令</li>`;
  };
  const go = (id?: string) => { if (!id) return; dlg.close(); run(id); };
  q.oninput = () => { sel = 0; render(); };
  q.onkeydown = e => {
    e.stopPropagation();
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, cur.length - 1); render(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); render(); }
    else if (e.key === "Enter") { e.preventDefault(); go(cur[sel]?.id); }
    else if (e.key === "Escape") { e.preventDefault(); dlg.close(); }
  };
  ul.onclick = e => go((e.target as HTMLElement).closest<HTMLElement>("[data-id]")?.dataset.id);
  dlg.onclick = e => { if (e.target === dlg) dlg.close(); };
  addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); e.stopImmediatePropagation(); if (dlg.open) dlg.close(); else { q.value = ""; sel = 0; render(); dlg.showModal(); q.focus(); } }
  }, true);
  return { open: () => { q.value = ""; render(); dlg.showModal(); q.focus(); } };
}
