// 工具箱界面（两层）：首页 = 按阶段分组的工具卡片（搜索 + 最近使用）；工具页 = 统一四块（参数 → 运行 → 结果 → 出错原因）+ 详情。
// 数据只来自声明（tooldecl.ts / 后端 tool_list，经 fieldmap.toToolList），这里没有任何工具专属逻辑：
// 工具的主操作按声明分三种——click（点原有控件）、hook（main 注册的函数）、mount（挂一个面板，如数据看板、串口工具）。
import { createElement, Terminal, Ruler, Binary, Cable, History, Zap, Cpu, Gauge, Activity, AudioWaveform, ScanLine, Bug, Server, Settings, Wrench, ArrowLeft, Search, LayoutDashboard } from "lucide";
import type { ToolCard, ToolList } from "./fieldmap";
import { TOOL_DECLS, type ToolDecl } from "./tooldecl";
import { buildList, groups, search, loadRecent, pushRecent, recentCards, reasonZh, fixFor, STATUS_ZH, STATUS_VARIANT, FIX_LABEL, SIDECAR_START_URL, INSTALLER_URL, type Conn } from "./toolmodel";

const ICONS: Record<string, any> = { terminal: Terminal, ruler: Ruler, binary: Binary, cable: Cable, history: History, zap: Zap, cpu: Cpu, gauge: Gauge, activity: Activity,
  "audio-waveform": AudioWaveform, "scan-line": ScanLine, bug: Bug, server: Server, settings: Settings, wrench: Wrench, "layout-dashboard": LayoutDashboard };
const ic = (n: string) => createElement(ICONS[n] ?? Wrench).outerHTML;
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
export type KV = { k: string; v: string };
export type Mount = (el: HTMLElement, api: ToolboxApi) => (() => void) | void;
export interface ToolboxApi { showResult(kv: KV[] | string): void; showError(code: string, message?: string, fix?: string): void; clearError(): void; confirm(changes: string[]): Promise<boolean> }
export interface ToolboxDeps { fix(action: string): void; fetchList?: () => Promise<any | null>; storage?: Storage | null }

export function initToolbox(deps: ToolboxDeps) {
  const page = document.getElementById("toolbox-m")!, home = document.getElementById("tb-home")!, tool = document.getElementById("tb-tool")!, hold = document.getElementById("tb-hold")!;
  const st = deps.storage === undefined ? (() => { try { return localStorage; } catch { return null; } })() : deps.storage;
  let conn: Conn = { sidecar: false, board: false }, stage = "req", q = "", openId: string | null = null, api: any | null = null, loaded = false, unmount: (() => void) | void;
  const hooks: Record<string, () => Promise<unknown> | unknown> = {}, mounts: Record<string, Mount> = {};
  let pendingConfirm: ((ok: boolean) => void) | null = null;
  const list = (): ToolList => buildList(api, conn, stage, loadRecent(st));
  const decl = (id: string): ToolDecl | undefined => TOOL_DECLS.find(d => d.id === id);

  const badge = (t: ToolCard) => `<wa-badge variant="${STATUS_VARIANT[t.status]}" appearance="outlined" pill>${STATUS_ZH[t.status]}</wa-badge>`;
  const card = (t: ToolCard) => `<button type="button" class="tb-card${t.status === "not_integrated" ? " dim" : ""}" data-tool="${esc(t.id)}">
      <span class="tb-ic">${ic(t.icon)}</span><span class="tb-tx"><b>${esc(t.name)}</b><span>${esc(t.summary)}</span></span>${badge(t)}</button>`;
  const sidecarBar = () => conn.sidecar ? "" : `<div class="tb-banner" role="status"><div><b>${esc(reasonZh("sidecar_down"))}</b><span>桌面版会自动启动本地服务；网页版需要本机先运行它。</span></div>
      <wa-button size="small" appearance="outlined" data-fix="start_sidecar">${FIX_LABEL.start_sidecar}</wa-button><a class="tb-link" href="${INSTALLER_URL}" target="_blank" rel="noopener">下载安装包</a></div>`;

  function renderHome() {
    if (!loaded) { home.innerHTML = `<div class="tb-head"><h2>工具箱</h2></div><div class="tb-grid">${"<wa-skeleton effect=\"sheen\" class=\"tb-sk\"></wa-skeleton>".repeat(6)}</div>`; return; }
    const l = list(), hits = search(l, q), rec = recentCards(l, loadRecent(st));
    const head = `<div class="tb-head"><h2>工具箱</h2><wa-input id="tb-q" type="search" size="small" placeholder="搜索工具：名字、用途、适用对象" with-clear value="${esc(q)}"><span slot="start">${createElement(Search).outerHTML}</span></wa-input></div>`;
    let body: string;
    if (q.trim()) body = hits.length ? `<div class="tb-sec"><h3>搜索结果 · ${hits.length}</h3><div class="tb-grid">${hits.map(card).join("")}</div></div>`
      : `<div class="tb-empty"><b>没有找到「${esc(q.trim())}」</b><span>换个关键词试试，比如「串口」「波形」「记录」。</span></div>`;
    else if (!l.tools.length) body = `<div class="tb-empty"><b>还没有可用的工具</b><span>工具清单由本地服务提供；先启动本地服务再打开工具箱。</span></div>`;
    else body = (rec.length ? `<div class="tb-sec"><h3>最近使用</h3><div class="tb-grid">${rec.map(card).join("")}</div></div>` : "")
      + groups(l).map(g => `<wa-details class="tb-grp" ${g.open ? "open" : ""} appearance="plain"><span slot="summary" class="tb-gs"><b>${esc(g.title)}</b><span class="tb-n">${g.tools.length}</span>${g.open ? '<span class="tb-cur">当前阶段</span>' : ""}</span><div class="tb-grid">${g.tools.map(card).join("")}</div></wa-details>`).join("");
    home.innerHTML = head + sidecarBar() + body;
    const qi = home.querySelector<any>("#tb-q");
    qi?.addEventListener("input", () => { q = String(qi.value ?? ""); const pos = q.length; renderHome(); const n = home.querySelector<any>("#tb-q"); n?.focus(); try { n?.setSelectionRange?.(pos, pos); } catch { /* */ } });
    qi?.addEventListener("wa-clear", () => { q = ""; renderHome(); });
  }

  function park() { for (const el of [...tool.querySelectorAll<HTMLElement>("[data-parked]")]) { el.removeAttribute("data-parked"); hold.append(el); } }
  function renderTool(id: string) {
    const l = list(), t = l.tools.find(x => x.id === id), d = decl(id);
    if (!t) { openId = null; return render(); }
    if (unmount) { unmount(); unmount = undefined; }
    park();
    const run = d?.run, ok = t.status === "available";
    const fix = t.fix ?? fixFor(t.reason); tool.dataset.st = t.status;
    tool.innerHTML = `<div class="tb-bar"><wa-button size="small" appearance="plain" id="tb-back">${createElement(ArrowLeft).outerHTML}返回工具箱</wa-button></div>
      <header class="tb-th"><span class="tb-ic lg">${ic(t.icon)}</span><div><h2>${esc(t.name)}</h2><p>${esc(t.summary)}</p>
        <div class="tb-meta">${badge(t)}${t.appliesTo.length ? `<span>适用：${esc(t.appliesTo.join("、"))}</span>` : ""}</div></div></header>
      ${ok ? "" : `<div class="tb-banner ${t.status === "not_integrated" ? "neutral" : ""}"><div><b>${esc(t.reason ? reasonZh(t.reason) : STATUS_ZH[t.status])}</b>${t.status === "not_integrated" ? `<span>负责：${esc(d?.owner ?? "待定")}。出处：${esc(t.source)}。接入前这里不提供假的运行结果。</span>` : ""}</div>${fix ? `<wa-button size="small" appearance="outlined" data-fix="${esc(fix)}">${esc(FIX_LABEL[fix] ?? fix)}</wa-button>` : ""}${fix === "start_sidecar" ? `<a class="tb-link" href="${INSTALLER_URL}" target="_blank" rel="noopener">下载安装包</a>` : ""}</div>`}
      <section class="tb-blk"><h3>参数</h3><div class="tb-params" id="tb-params">${d?.ui?.length ? "" : '<p class="tb-muted">这个工具不需要参数。</p>'}</div></section>
      <section class="tb-blk tb-run"><wa-button variant="brand" id="tb-run" ${ok && run ? "" : "disabled"}>${esc(run?.label ?? "运行")}</wa-button>
        ${run?.writes || run?.touches_board ? `<span class="tb-muted">${run.writes ? "会写文件" : "会动板子"}：运行前先给你看改动并确认</span>` : ""}<div id="tb-confirm"></div></section>
      <section class="tb-blk"><h3>结果</h3><div id="tb-result" class="tb-result"><p class="tb-muted">运行后结果显示在这里。</p></div></section>
      <section class="tb-blk" id="tb-errblk" hidden><h3>出错原因</h3><div id="tb-err"></div></section>
      <wa-details class="tb-det" summary="详情" appearance="plain"><dl class="tb-dl"><dt>工具 id</dt><dd><code>${esc(t.id)}</code></dd><dt>阶段</dt><dd>${esc(l.stages.find(s => s.id === t.stage)?.title ?? t.stage)}</dd>
        <dt>Agent 可调用</dt><dd>${t.agent ? "是" : "否"}</dd><dt>出处</dt><dd>${esc(t.source || "—")}</dd><dt>许可</dt><dd>${esc(t.license || "—")}</dd>${d?.detail ? `<dt>说明</dt><dd>${esc(d.detail)}</dd>` : ""}${t.reason ? `<dt>原因码</dt><dd><code>${esc(t.reason)}</code></dd>` : ""}</dl></wa-details>`;
    const params = tool.querySelector<HTMLElement>("#tb-params")!;
    for (const uid of d?.ui ?? []) { const el = document.getElementById(uid); if (el && el.id !== run?.click) { el.setAttribute("data-parked", ""); params.append(el); } }
    if (run?.click) { const el = document.getElementById(run.click); if (el) { el.setAttribute("data-parked", ""); el.hidden = true; tool.append(el); } }
    tool.querySelector("#tb-back")!.addEventListener("click", () => { openId = null; render(); });
    tool.querySelector("#tb-run")!.addEventListener("click", () => void doRun(t, d));
  }
  async function doRun(t: ToolCard, d: ToolDecl | undefined) {
    const run = d?.run; if (!run) return;
    A.clearError();
    if ((run.writes || run.touches_board) && !(await A.confirm([run.changes_zh ?? (run.writes ? "会写文件" : "会改变板子状态")]))) return;
    pushRecent(st, t.id);
    try {
      if (run.click) document.getElementById(run.click)?.click();
      else if (run.hook) { const h = hooks[run.hook]; if (!h) return A.showError("not_integrated"); await h(); }
      else if (run.mount) { const m = mounts[run.mount], res = tool.querySelector<HTMLElement>("#tb-result")!; if (!m) return A.showError("not_integrated"); if (unmount) unmount(); res.innerHTML = ""; unmount = m(res, A); }
    } catch (e: any) { A.showError(String(e?.code || "error"), e?.message, e?.fix_action); }
  }
  const A: ToolboxApi = {
    showResult(kv) { const r = tool.querySelector<HTMLElement>("#tb-result"); if (!r) return; r.innerHTML = typeof kv === "string" ? `<p>${esc(kv)}</p>` : `<dl class="tb-dl">${kv.map(x => `<dt>${esc(x.k)}</dt><dd>${esc(x.v)}</dd>`).join("")}</dl>`; },
    showError(code, message, fix) {
      const b = tool.querySelector<HTMLElement>("#tb-errblk"), e = tool.querySelector<HTMLElement>("#tb-err"); if (!b || !e) return;
      const f = fix || fixFor(code);
      e.innerHTML = `<div class="tb-banner"><div><b>${esc(reasonZh(code))}</b>${message ? `<span>${esc(message)}</span>` : ""}</div>${f ? `<wa-button size="small" appearance="outlined" data-fix="${esc(f)}">${esc(FIX_LABEL[f] ?? f)}</wa-button>` : ""}</div>`;
      b.hidden = false;
    },
    clearError() { const b = tool.querySelector<HTMLElement>("#tb-errblk"); if (b) b.hidden = true; },
    confirm(changes) {
      const c = tool.querySelector<HTMLElement>("#tb-confirm"); if (!c) return Promise.resolve(true);
      pendingConfirm?.(false);
      c.innerHTML = `<div class="tb-confirm"><b>确认后才会执行：</b><ul>${changes.map(x => `<li>${esc(x)}</li>`).join("")}</ul><wa-button size="small" appearance="outlined" data-cf="1">确认执行</wa-button><wa-button size="small" appearance="plain" data-cf="0">取消</wa-button></div>`;
      return new Promise(res => { pendingConfirm = ok => { pendingConfirm = null; c.innerHTML = ""; res(ok); }; });
    },
  };
  page.addEventListener("click", e => {
    const el = e.target as HTMLElement;
    const cf = el.closest<HTMLElement>("[data-cf]"); if (cf) { pendingConfirm?.(cf.dataset.cf === "1"); return; }
    const fx = el.closest<HTMLElement>("[data-fix]"); if (fx) { const a = fx.dataset.fix!; if (a === "start_sidecar") location.href = SIDECAR_START_URL; else deps.fix(a); return; }
    const c = el.closest<HTMLElement>("[data-tool]"); if (c) { openId = c.dataset.tool!; pushRecent(st, openId); render(); }
  });
  function render() { home.hidden = !!openId; tool.hidden = !openId; if (openId) { if (tool.dataset.open !== openId) { tool.dataset.open = openId; renderTool(openId); } else refreshToolStatus(); } else { tool.dataset.open = ""; if (unmount) { unmount(); unmount = undefined; } park(); renderHome(); } }
  function refreshToolStatus() { const t = list().tools.find(x => x.id === openId); const cur = tool.dataset.st; if (t && cur !== t.status) { tool.dataset.st = t.status; tool.dataset.open = ""; render(); } }
  async function refreshApi() { try { api = (await deps.fetchList?.()) ?? null; } catch { api = null; } loaded = true; if (!page.hidden) render(); }
  const btn = document.getElementById("toolbox")!;
  const setOpen = (o: boolean) => { page.hidden = !o; btn.classList.toggle("on", o); btn.setAttribute("aria-expanded", String(o)); document.body.classList.toggle("tb-open", o); if (o) { void refreshApi(); render(); } };
  btn.addEventListener("click", () => setOpen(page.hidden));
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !page.hidden) { if (openId) { openId = null; render(); } else setOpen(false); } });
  return {
    ...A,
    open: (id?: string) => { setOpen(true); if (id) { openId = id; render(); } },
    close: () => setOpen(false),
    setConn(c: Conn) { const ch = c.sidecar !== conn.sidecar || c.board !== conn.board; conn = c; if (ch && !page.hidden) { if (openId) refreshToolStatus(); else renderHome(); } },
    setStage(s: string) { if (s !== stage) { stage = s; if (!page.hidden && !openId) renderHome(); } },
    registerHook(name: string, f: () => Promise<unknown> | unknown) { hooks[name] = f; },
    registerMount(name: string, f: Mount) { mounts[name] = f; },
  };
}
export type Toolbox = ReturnType<typeof initToolbox>;
