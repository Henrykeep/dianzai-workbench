// 测量与历史（docs/26 §3.5）：A/B 光标读数、t0 阶跃锚点、每轮实验进历史、上一轮做余辉。
// 只依赖 Plot 的公开接口和两个取值函数，界面不认任何题目字段名。
import { Plot, num } from "./plot";
import { measure, stepMetrics, StepM } from "./measure";
import { acceptEval, worstOf, AcceptR, AcceptSpec } from "./accept";
import { VERDICT_SHORT } from "./round";

export type Loop = { name: string; y: string; gains?: string[]; note?: string };
type Run = { n: number; wall: string; dur: number; params: Record<string, number>; diff: string; data: ReturnType<Plot["capture"]>; m: StepM | null; a: AcceptR | null; layer: string; verdict?: string };
const $ = (id: string) => document.getElementById(id)!;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const f = (v: number) => Number.isFinite(v) ? num(v) : "—";
const MAX_RUNS = 20;

// 被控量：选了串级的某一层就是那层的 y；否则第一条叠着设定值的可见通道（schema 的 ref_for 决定，界面不认字段名）
let PLOT: Plot, ACC: AcceptSpec[] = [], LOOPS: Loop[] = [], LAYER = -1;
function mainCh(plot: Plot) {
  if (LAYER >= 0) { const i = plot.names.indexOf(LOOPS[LAYER].y); return i >= 0 && plot.refOf[i] >= 0 ? i : -1; }
  return plot.refOf.findIndex((r, i) => r >= 0 && plot.vis[i]);
}
const specOf = (i: number) => i < 0 ? undefined : ACC.find(a => a.y === PLOT.names[i]);
function metricsOf(g: { rel: number[]; ys: number[][] }) {
  const i = mainCh(PLOT); if (i < 0) return null;
  return stepMetrics(g.rel, g.ys[i], g.ys[PLOT.refOf[i]]);
}
function acceptOf(g: { rel: number[]; ys: number[][] }) {
  const i = mainCh(PLOT), a = specOf(i); if (!a) return null;
  return acceptEval(g.rel, g.ys[i], g.ys[PLOT.refOf[i]], a);
}
const layerName = () => LAYER >= 0 ? LOOPS[LAYER].name : "";
const ms = (s: number) => Number.isFinite(s) ? (s < 1 ? (s * 1000).toFixed(0) : s.toFixed(2)) : "—";
const msu = (s: number) => Number.isFinite(s) && s < 1 ? "ms" : "s";

export function initAnalysis(plot: Plot, params: () => Record<string, number>, onNotify: (side: string) => void) {
  PLOT = plot;
  const runs: Run[] = [];
  let t0Params: Record<string, number> = {};

  let open = false;                       // t0 之后这一轮还没记进台账
  // 结束这一轮：截下来进台账；余辉换成上一轮，读数和它比；主通道上标 Mp / ts
  type SM = { ok?: boolean; overshoot_pct?: number; rise_s?: number | null; settling_s?: number | null; sse_pct?: number };
  function closeRound(verdict?: string, sm?: SM) {
    if (plot.t0 == null || !open) return;
    const now = plot.now(), dur = Math.min(now - plot.t0, 30), prev = runs[0]?.params ?? {};
    const diff = Object.keys(t0Params).filter(k => prev[k] !== undefined && prev[k] !== t0Params[k])
      .map(k => `${k} ${num(prev[k])}→${num(t0Params[k])}`).join("，");
    const r: Run = { m: null, a: null, layer: layerName(), n: (runs[0]?.n ?? 0) + 1, wall: new Date().toLocaleTimeString("zh-CN", { hour12: false }), dur, params: t0Params, diff, data: plot.capture(plot.t0, dur), verdict };
    r.data.label = `#${r.n}`; r.m = metricsOf(r.data); r.a = acceptOf(r.data);
    // 阶跃实验：用侧车同一份指标（和程序判定一致），界面自己算的只在手动 t0 时用
    if (sm?.ok) r.m = { Mp: sm.overshoot_pct ?? NaN, tr: sm.rise_s ?? NaN, ts: sm.settling_s ?? NaN, ess: sm.sse_pct ?? NaN, settled: sm.settling_s != null, t0: NaN };
    runs.unshift(r); runs.length = Math.min(runs.length, MAX_RUNS);
    open = false;
    plot.ghost = runs[1]?.data ?? null;
    annotate(r);
    renderHist(); renderReads(); onNotify("hist");
  }
  function annotate(r: Run) {
    const i = mainCh(plot);
    if (i < 0 || !r.m || plot.t0 == null) { plot.annot = null; plot.repaint(); return; }
    const y = r.data.ys[i], s = r.data.ys[plot.refOf[i]];
    let j0 = 0, sv = NaN;                // 最后一次设定值跳变 = 阶跃时刻（跳过 NaN：设定值通道不是每帧都有）
    for (let j = 0; j < s.length; j++) { if (!Number.isFinite(s[j])) continue; if (Number.isFinite(sv) && s[j] !== sv) j0 = j; sv = s[j]; }
    if (!j0) {
      const last = y[y.length - 1] ?? 0; let jm = 0;
      y.forEach((v, j) => { if (Math.abs(v - last) > Math.abs(y[jm] - last)) jm = j; }); j0 = jm;
    }
    const tStep = plot.t0 + (r.data.rel[j0] ?? 0);
    const up = (y[y.length - 1] ?? 0) >= (y[j0] ?? 0);   // 阶跃方向：终值相对跳变时刻
    let k = j0; for (let j = j0; j < y.length; j++) if (Number.isFinite(y[j]) && (up ? y[j] > y[k] : y[j] < y[k])) k = j;
    plot.annot = { i, tPeak: plot.t0 + r.data.rel[k], yPeak: y[k], mp: r.m.Mp, ts: r.m.settled ? tStep + r.m.ts : null, tsv: r.m.ts };
    plot.repaint();
  }
  window.addEventListener("dz-round", e => { const d = (e as CustomEvent).detail; closeRound(VERDICT_SHORT[d?.verdict?.action] ?? undefined, d?.metrics); });
  function markT0() {
    if (!plot.t.length) return;
    const now = plot.now();
    closeRound();                        // 手动标 t0：上一轮还没结束就先记进台账
    t0Params = { ...params() }; open = true; plot.annot = null;
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
    const cur0 = plot.t0 == null || i < 0 ? null : metricsOf(plot.capture(plot.t0, Math.min(plot.now() - plot.t0, 30)));
    // 保持类任务设定值不变，没有阶跃指标，但验收照样能判
    const cur = cur0 ?? (specOf(i) && plot.t0 != null ? { Mp: NaN, tr: NaN, ts: NaN, ess: NaN, settled: false, t0: 0 } : null);
    host.hidden = !cur;
    if (!cur) return;
    const g = runs.find(r => r.data === plot.ghost)?.m ?? null;
    const sp = specOf(i), acc = sp ? acceptOf(plot.capture(plot.t0!, Math.min(plot.now() - plot.t0!, 30))) : null;
    const u = esc(plot.units[i]);
    // 有验收规格：先摆评委口径（判定 / 到位 / 到位后误差），教科书指标留超调和调节做调参参考
    const head = !sp ? "" : `<div class="rd acc ${acc?.pass ? "ok" : "bad"}" title="${esc(sp.name ?? "")}：±${sp.band} ${u}${sp.vmax != null ? `，|v|≤${sp.vmax} ${u}/s` : ""}，保持 ${(sp.hold_s ?? .3) * 1000} ms${sp.t_max_s != null ? `，限时 ${sp.t_max_s} s` : ""}"><span class="cap">验收</span><span class="v">${acc?.pass ? "通过" : "未过"}</span><span class="dt">${esc(acc?.why || `${acc?.segs.length ?? 0} 段`)}</span></div>
      <div class="rd"><span class="cap">到位</span><span class="v">${acc && Number.isFinite(acc.total) ? acc.total.toFixed(2) : "…"}<small>s</small></span><span class="dt">${sp.t_max_s != null ? `限 ${sp.t_max_s} s` : "&nbsp;"}</span></div>
      <div class="rd"><span class="cap">到位后误差</span><span class="v">${acc && Number.isFinite(acc.worst_err) ? num(acc.worst_err) : "…"}<small>${u}</small></span><span class="dt">限 ±${sp.band}</span></div>`;
    const it0: [string, string, string, number, number, boolean][] = [
      ["超调", Number.isFinite(cur.Mp) ? cur.Mp.toFixed(1) : "—", "%", cur.Mp, g?.Mp ?? NaN, false],
      ["上升", ms(cur.tr), msu(cur.tr), cur.tr, g?.tr ?? NaN, false],
      ["调节", cur.settled ? ms(cur.ts) : "…", cur.settled ? msu(cur.ts) : cur0 ? "未稳" : "", cur.ts, g?.ts ?? NaN, !cur.settled],
      ["稳态误差", cur.ess.toFixed(1), "%", cur.ess, g?.ess ?? NaN, false]];
    const it = sp ? it0.filter(x => x[0] === "超调" || x[0] === "调节") : it0;
    host.innerHTML = `<span class="rn mono">${esc((layerName() ? layerName() + " · " : "") + plot.names[i])}</span>` + head + it.map(([k, v, u, x, y, wait]) => {
      const d = x - y, good = d < 0, show = Number.isFinite(d) && !wait;
      const dd = show ? (u === "%" ? d.toFixed(1) : u === "ms" ? (d * 1000).toFixed(0) : d.toFixed(2)) : "";
      return `<div class="rd"><span class="cap">${k}</span><span class="v">${v}<small>${u}</small></span>
        <span class="dt">${show ? `比 ${esc(plot.ghost!.label)} <b class="${d === 0 ? "" : good ? "ok-t" : "bad-t"}">${d > 0 ? "+" : ""}${dd}</b>` : "&nbsp;"}</span></div>`;
    }).join("");
  }

  function renderHist() {
    const host = $("hist"), ln = layerName(), rs = runs.filter(r => r.layer === ln), sp = specOf(mainCh(plot));
    $("hist-n").textContent = runs.length ? `${rs.length}${ln ? " 轮 · " + ln : " 轮"}` : "";
    if (!runs.length) { host.innerHTML = `<p class="hint">每点一次“阶跃实验”，这一轮的改动和超调 / 上升 / 调节自动记到这里；上一轮淡色画在曲线上对比。只存在内存里。</p>`; return; }
    // 台账：每轮一行，改动 + 三个指标，当前余辉轮左侧黄铜边
    // 串级：每层一本台账（只列在当前层做的轮次）；有验收规格时列评委口径 + 最近 N 轮按最差一轮的汇总
    const w = sp ? worstOf(rs.map(r => r.a), sp.runs ?? 3) : null, u = sp ? esc(plot.units[mainCh(plot)]) : "";
    const sum = !w ? "" : `<p class="acc-sum ${w.all ? "ok" : ""}">最近 ${w.n}/${w.need} 轮：通过 ${w.pass} · 最差到位 ${Number.isFinite(w.total) ? w.total.toFixed(2) + " s" : "—"} · 最差误差 ${Number.isFinite(w.err) ? num(w.err) + " " + u : "—"}${w.all ? " · 达标" : ""}</p>`;
    const tm = (v: number | undefined) => v != null && Number.isFinite(v) ? ms(v) + " " + msu(v) : "—";
    const judge = (r: Run) => sp ? (r.a ? (r.a.pass ? "过" : "未过") : "—") : r.verdict ?? "—";
    host.innerHTML = sum + `<table class="ledger"><tr><th>轮</th><th>改动</th><th>超调</th><th>上升</th><th>调节</th><th>判定</th></tr>` + rs.map(r => { const k = runs.indexOf(r); return `<tr class="${r === rs[0] ? "cur" : ""} ${plot.ghost === r.data ? "on" : ""}" data-g="${k}" title="${esc(r.wall + (r.a?.why ? " · " + r.a.why : ""))}；点一行 = 把这一轮当余辉对比">
      <td class="hn">#${r.n}</td><td class="chg">${r.diff ? esc(r.diff) : r === rs[rs.length - 1] ? "首轮" : "参数未变"}</td>
      <td class="num mp">${r.m ? r.m.Mp.toFixed(1) + "%" : "—"}</td><td class="num">${tm(r.m?.tr)}</td><td class="num ts">${r.m?.settled ? tm(r.m.ts) : "—"}</td>
      <td class="${judge(r) === "达标" || judge(r) === "过" ? "ok-t" : ""}">${esc(judge(r))}</td></tr>`; }).join("") + `</table>`;
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
  // 串级分层（schema 的 loops，内环在前）：选一层 = 读数/台账/验收都换成这层的 y，参数筛到这层的增益
  const sel = $("layer") as HTMLSelectElement;
  sel.onchange = () => { LAYER = +sel.value; onLayer(LAYER >= 0 ? LOOPS[LAYER] : null); renderHist(); renderReads(); };
  let onLayer: (l: Loop | null) => void = () => {};
  return { setSpec(acc: AcceptSpec[], loops: Loop[], cb: (l: Loop | null) => void) {
      ACC = acc; LOOPS = loops; LAYER = -1; onLayer = cb; cb(null);          // 换工程：清掉上一个工程的分层筛选
      sel.hidden = !loops.length;
      sel.innerHTML = `<option value="-1">全部</option>` + loops.map((l, k) => `<option value="${k}" title="${esc(l.note ?? "")}">${k + 1}. ${esc(l.name)}</option>`).join("");
      renderHist(); renderReads();
    },
    reset() { runs.length = 0; t0Params = {}; renderHist(); renderMeas(); renderReads(); }, runs: () => runs.length, marked: () => plot.t0 != null };
}
