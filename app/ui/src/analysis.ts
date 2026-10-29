// 测量与历史（docs/26 §3.5）：A/B 光标读数、t0 阶跃锚点、每轮实验进历史、上一轮做余辉。
// 只依赖 Plot 的公开接口和两个取值函数，界面不认任何题目字段名。
import { Plot, num } from "./plot";
import { measure, stepMetrics, StepM } from "./measure";

type Run = { n: number; wall: string; dur: number; params: Record<string, number>; diff: string; data: ReturnType<Plot["capture"]>; m: StepM | null };
const $ = (id: string) => document.getElementById(id)!;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const f = (v: number) => Number.isFinite(v) ? num(v) : "—";
const MAX_RUNS = 20;

// 被控量 = 第一条叠着设定值的可见通道（schema 的 ref_for 决定，界面不认字段名）；没有就不出阶跃读数
function mainCh(plot: Plot) { return plot.refOf.findIndex((r, i) => r >= 0 && plot.vis[i]); }
let PLOT: Plot;
function metricsOf(g: { rel: number[]; ys: number[][] }) {
  const i = mainCh(PLOT); if (i < 0) return null;
  return stepMetrics(g.rel, g.ys[i], g.ys[PLOT.refOf[i]]);
}
const ms = (s: number) => Number.isFinite(s) ? (s < 1 ? (s * 1000).toFixed(0) : s.toFixed(2)) : "—";
const msu = (s: number) => Number.isFinite(s) && s < 1 ? "ms" : "s";

export function initAnalysis(plot: Plot, params: () => Record<string, number>, onNotify: (side: string) => void) {
  PLOT = plot;
  const runs: Run[] = [];
  let t0Params: Record<string, number> = {};

  function markT0() {
    if (!plot.t.length) return;
    const now = plot.now();
    if (plot.t0 != null) {               // 结束上一轮：截下来进历史，并作为余辉
      const dur = Math.min(now - plot.t0, 30), prev = runs[0]?.params ?? {};
      const diff = Object.keys(t0Params).filter(k => prev[k] !== undefined && prev[k] !== t0Params[k])
        .map(k => `${k} ${num(prev[k])}→${num(t0Params[k])}`).join("，");
      const r: Run = { m: null, n: (runs[0]?.n ?? 0) + 1, wall: new Date().toLocaleTimeString("zh-CN", { hour12: false }), dur, params: t0Params, diff, data: plot.capture(plot.t0, dur) };
      r.data.label = `#${r.n}`; r.m = metricsOf(r.data);
      runs.unshift(r); runs.length = Math.min(runs.length, MAX_RUNS);
      plot.ghost = r.data;
      renderHist(); onNotify("hist");
    }
    t0Params = { ...params() };
    plot.setAnchor(now);
    renderMeas(); renderReads();
  }

  function renderMeas() {
    const [A, B] = plot.cur, host = $("meas");
    $("meas-t0").textContent = plot.t0 == null ? "" : `t0 已标记 · 余辉 ${plot.ghost?.label ?? "无"}`;
    if (A == null) { host.innerHTML = `<p class="hint">在曲线上<b>单击</b>放 A，<b>Shift+单击</b>放 B，双击清除。<br>按 <kbd>T</kbd> 标记阶跃起点 t0；下次再标时上一轮进“历史”并显示成余辉。</p>`; return; }
    const ref = plot.t0 ?? plot.now(), rel = (x: number) => (x - ref >= 0 && plot.t0 != null ? "+" : "") + (x - ref).toFixed(3) + " s";
    let head = `<div class="mrow mh"><span>A</span><span class="mono">${rel(A)}</span></div>`;
    if (B != null) {
      const dt = Math.abs(B - A);
      head += `<div class="mrow mh"><span>B</span><span class="mono">${rel(B)}</span></div>
        <div class="mrow mh"><span>Δt</span><span class="mono">${(dt * 1000).toFixed(1)} ms</span></div>
        <div class="mrow mh"><span>1/Δt</span><span class="mono">${dt > 0 ? num(1 / dt) + " Hz" : "—"}</span></div>`;
    }
    const rows = measure(plot.t, plot.ys, A, B ?? A, plot.laneIdx());
    host.innerHTML = head + `<div class="mtab"><span></span><span>A</span><span>B</span><span>Δ</span>` + rows.map(r =>
      `<b class="mn" title="${esc(plot.names[r.i])}"><i style="--c:var(--ch${(r.i % 8) + 1})"></i>${esc(plot.names[r.i])}</b><span class="mono">${f(r.a)}</span><span class="mono">${B == null ? "" : f(r.b)}</span><span class="mono">${B == null ? "" : f(r.d)}</span>` +
      (B == null ? "" : `<span class="mx mono">区间 ${f(r.min)} … ${f(r.max)} · 均值 ${f(r.mean)} ${esc(plot.units[r.i])}</span>`)).join("") + `</div>`;
  }

  // 读数条（docs/26 §6）：本轮（t0 起）超调 / 上升 / 调节，大号细体；和余辉轮比，只有变好才标绿
  function renderReads() {
    const host = $("reads"), i = mainCh(plot);
    const cur = plot.t0 == null || i < 0 ? null : metricsOf(plot.capture(plot.t0, Math.min(plot.now() - plot.t0, 30)));
    host.hidden = !cur;
    if (!cur) return;
    const g = runs.find(r => r.data === plot.ghost)?.m ?? null;
    const it: [string, string, string, number, number, boolean][] = [
      ["超调", cur.Mp.toFixed(1), "%", cur.Mp, g?.Mp ?? NaN, false],
      ["上升", ms(cur.tr), msu(cur.tr), cur.tr, g?.tr ?? NaN, false],
      ["调节", cur.settled ? ms(cur.ts) : "…", cur.settled ? msu(cur.ts) : "未稳", cur.ts, g?.ts ?? NaN, !cur.settled],
      ["稳态误差", cur.ess.toFixed(1), "%", cur.ess, g?.ess ?? NaN, false]];
    host.innerHTML = `<span class="rn mono">${esc(plot.names[i])}</span>` + it.map(([k, v, u, x, y, wait]) => {
      const d = x - y, good = d < 0, show = Number.isFinite(d) && !wait;
      const dd = show ? (u === "%" ? d.toFixed(1) : u === "ms" ? (d * 1000).toFixed(0) : d.toFixed(2)) : "";
      return `<div class="rd"><span class="cap">${k}</span><span class="v">${v}<small>${u}</small></span>
        <span class="dt">${show ? `比 ${esc(plot.ghost!.label)} <b class="${good ? "ok-t" : ""}">${d > 0 ? "+" : ""}${dd}</b>` : "&nbsp;"}</span></div>`;
    }).join("");
  }

  function renderHist() {
    const host = $("hist");
    $("hist-n").textContent = runs.length ? `${runs.length} 轮` : "";
    if (!runs.length) { host.innerHTML = `<p class="hint">每次按 <kbd>T</kbd> 或点“阶跃实验”标一个 t0；再标下一次时，上一轮的曲线和当时的参数记到这里，可以拿来做余辉对比。只存在内存里。</p>`; return; }
    // 台账：每轮一行，改动 + 三个指标，当前余辉轮左侧黄铜边
    host.innerHTML = `<table class="ledger"><tr><th>轮</th><th>超调</th><th>上升</th><th>调节</th><th></th></tr>` + runs.map((r, k) => `<tr class="${plot.ghost === r.data ? "on" : ""}">
      <td class="hn">#${r.n}</td><td>${r.m ? r.m.Mp.toFixed(1) + "%" : "—"}</td><td>${r.m ? ms(r.m.tr) + " " + msu(r.m.tr) : "—"}</td><td>${r.m?.settled ? ms(r.m.ts) + " " + msu(r.m.ts) : "—"}</td>
      <td><button class="btn ghost sm" data-g="${k}">${plot.ghost === r.data ? "余辉中" : "余辉"}</button></td></tr>
      <tr class="hd"><td></td><td colspan="4">${r.diff ? esc(r.diff) : k === runs.length - 1 ? "首轮" : "参数未变"} · ${r.wall}</td></tr>`).join("") + `</table>`;
  }
  $("hist").addEventListener("click", e => {
    const b = (e.target as HTMLElement).closest<HTMLElement>("[data-g]"); if (!b) return;
    const r = runs[+b.dataset.g!]; plot.ghost = plot.ghost === r.data ? null : r.data;
    if (plot.t0 == null && plot.ghost) plot.setAnchor(plot.now() - plot.win * .8);   // 余辉要对齐到一个 t0
    plot.setAnchor(plot.t0); renderHist(); renderMeas(); renderReads();
  });

  $("t0-mark").onclick = markT0;
  $("ag-step").addEventListener("click", markT0);            // 阶跃实验的起点就是 t0
  $("cur-clr").onclick = () => { plot.cur = [null, null]; plot.ghost = null; plot.setAnchor(null); plot.setCursor(0, null); renderHist(); renderReads(); };
  window.addEventListener("dz-cursor", () => { renderMeas(); if (plot.cur[0] != null) onNotify("meas"); });
  document.addEventListener("keydown", e => {
    if ((e.target as HTMLElement).matches("input,select,textarea") || e.ctrlKey || e.metaKey) return;
    if (e.key === "t" || e.key === "T") markT0();
  });
  setInterval(() => { if (plot.cur[0] != null) renderMeas(); if (plot.t0 != null && plot.running) renderReads(); }, 500);
  renderMeas(); renderHist();
  return { reset() { runs.length = 0; t0Params = {}; renderHist(); renderMeas(); renderReads(); }, runs: () => runs.length, marked: () => plot.t0 != null };
}
