// 评分页（产品逻辑重组 · 评分页）：评分项来自 requirements.yaml，判定用 app.yaml 的 accept 规格（accept.ts，与侧车 accept.py 同一定义）。
// 每项跑 N 轮：开始 / 结束用按钮，或用遥测条件（如 run > 0.5 开始、跑满 X 秒或条件不再成立结束）；每轮自动计时、判到位，N 轮按最差一轮判。
// 证据：每轮 CSV + 曲线截图 + result.json，经侧车 score_save 存到 docs/verify/<题号>/logs/（目录由 tools/req.py newlog 建）。
// 表格结构借 DS-land-and-air《D题 V23 联调与计分矩阵》的“得分验收矩阵”：评分项 | 自动判定 | 人工 / 物理证据 | 当前结论（默认未验收）。
import { acceptEval, worstOf, type AcceptSpec, type AcceptR } from "./accept";
import type { Plot } from "./plot";
type Call = <T = any>(op: string, a?: Record<string, unknown>) => Promise<T>;
type Metric = { name: string; op?: string; value?: number; unit?: string; how?: string; accept?: string; test_id?: string };
export type ScoreItem = { id: string; part?: string; score?: number; text: string; metrics: Metric[]; evidence: unknown[] };
export type Run = { n: number; dur: number; r: AcceptR | null; csv: string; png?: string };
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const f2 = (x: number) => Number.isFinite(x) ? x.toFixed(2) : "—";

// ---- 纯函数（单测用）
export const condOk = (v: number, op: string, x: number) => Number.isFinite(v) && (op === ">" ? v > x : op === "<" ? v < x : op === ">=" ? v >= x : op === "<=" ? v <= x : Math.abs(v - x) < 1e-9);
export function csvOf(rel: number[], names: string[], ys: number[][]) {
  return ["t_s," + names.join(","), ...rel.map((t, k) => [t.toFixed(4), ...ys.map(y => Number.isFinite(y[k]) ? +y[k].toPrecision(7) : "")].join(","))].join("\n") + "\n";
}
// 一项的结论：DS 矩阵的口径，默认“未验收”，只有现场层（field）N 轮全过才算“现场通过”
export function verdict(runs: Run[], need: number, layer: string) {
  const w = worstOf(runs.map(r => r.r), need);
  if (!w) return { text: "未验收", cls: "", w };
  if (w.n < need) return { text: `已跑 ${w.n}/${need} 轮`, cls: "", w };
  if (!w.all) return { text: `未过（${w.pass}/${w.n}）`, cls: "bad", w };
  return layer === "field" ? { text: "现场通过", cls: "ok", w } : { text: `${layer === "sim" ? "仿真" : "台架"}通过（未现场验收）`, cls: "ok", w };
}
// 证据图的分格：每个显示中的通道一格，它的设定值通道画在同一格（虚线），设定值通道本身不单独占格
export function lanesOf(names: string[], refOf: number[], vis: boolean[]) {
  const isRef = new Set(refOf.filter(r => r >= 0));
  return names.map((_, i) => i).filter(i => vis[i] !== false && !isRef.has(i)).map(i => ({ y: i, ref: refOf[i] ?? -1 }));
}
// 证据图：只画这一轮截取的那段（t 从 0 开始），每格写通道名和单位、标题写评分项和轮次
export function snapRun(rel: number[], ys: number[][], names: string[], units: string[], refOf: number[], vis: boolean[], title: string): string | undefined {
  const L = lanesOf(names, refOf, vis); if (!L.length || rel.length < 2) return;
  const W = 900, LH = 150, TOP = 28, BOT = 24, PADL = 60, PADR = 12, H = TOP + L.length * LH + BOT;
  const o = document.createElement("canvas"); o.width = W; o.height = H; const g = o.getContext("2d")!;
  g.fillStyle = "#111"; g.fillRect(0, 0, W, H); g.font = "13px sans-serif"; g.fillStyle = "#ddd"; g.fillText(title, 8, 18);
  const t0 = rel[0], t1 = rel[rel.length - 1], X = (t: number) => PADL + (t - t0) / (t1 - t0 || 1) * (W - PADL - PADR);
  L.forEach((ln, k) => {
    const y0 = TOP + k * LH, ser = [ys[ln.y], ln.ref >= 0 ? ys[ln.ref] : []];
    const all = ser.flat().filter(Number.isFinite); let lo = Math.min(...all), hi = Math.max(...all);
    if (!all.length) { lo = -1; hi = 1; } if (hi - lo < 1e-9) { lo -= 1; hi += 1; } const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const Y = (v: number) => y0 + 8 + (hi - v) / (hi - lo) * (LH - 24);
    g.strokeStyle = "#333"; g.strokeRect(PADL, y0 + 8, W - PADL - PADR, LH - 24);
    g.fillStyle = "#888"; g.font = "11px monospace"; g.fillText(hi.toPrecision(3), 4, y0 + 18); g.fillText(lo.toPrecision(3), 4, y0 + LH - 18);
    ser.forEach((a, si) => { if (!a.length) return; g.strokeStyle = si ? "#c9a24a" : "#6cc"; g.setLineDash(si ? [5, 4] : []); g.beginPath();
      let pen = false; rel.forEach((t, q) => { const v = a[q]; if (!Number.isFinite(v)) { pen = false; return; } pen ? g.lineTo(X(t), Y(v)) : g.moveTo(X(t), Y(v)); pen = true; }); g.stroke(); });
    g.setLineDash([]); g.font = "12px sans-serif"; g.fillStyle = "#6cc";
    g.fillText(`${names[ln.y]}${units[ln.y] ? ` (${units[ln.y]})` : ""}`, PADL + 6, y0 + 22);
    if (ln.ref >= 0) { g.fillStyle = "#c9a24a"; g.fillText(`- - ${names[ln.ref]}`, PADL + 6, y0 + 38); }
  });
  g.fillStyle = "#888"; g.font = "11px monospace";
  for (let q = 0; q <= 5; q++) { const t = t0 + (t1 - t0) * q / 5; g.fillText(t.toFixed(2) + " s", X(t) - 18, H - 8); }
  return o.toDataURL("image/png");
}

export function initScore(call: Call, plot: Plot, specs: () => AcceptSpec[], toast: (t: string, k?: "ok" | "warn") => void) {
  const root = document.getElementById("score"); if (!root) return { refresh() {} };
  let items: ScoreItem[] = [], code = "", cur: ScoreItem | null = null;
  const runs = new Map<string, Run[]>(), saved = new Map<string, string>();
  let arm: null | { t0: number | null; timer: number } = null;
  const $ = <T extends HTMLElement = HTMLInputElement>(id: string) => document.getElementById(id) as unknown as T;

  async function refresh(path?: string) {
    const r = await call<any>("score_items", path ? { path } : {}).catch(() => null);
    if (!r) { $("sc-mat").innerHTML = `<p class="hint">读不到评分项：先在项目页第 ① 步读题。</p>`; return; }
    items = r.items; code = r.code; if (cur) cur = items.find(x => x.id === cur!.id) ?? null;
    $<HTMLSelectElement>("sc-file").innerHTML = (r.candidates as string[]).map(c => `<option${c === r.path ? " selected" : ""}>${esc(c)}</option>`).join("") || `<option>${esc(r.path)}</option>`;
    if (cur && !arm) pick(cur.id); else drawMat();
  }
  const specFor = (it: ScoreItem) => { const nm = it.metrics.find(m => m.accept)?.accept; return specs().find(s => s.name === nm) ?? null; };
  function drawMat() {
    const layer = $<HTMLSelectElement>("sc-layer").value;
    $("sc-mat").innerHTML = `<table class="pf-tab sc-mat"><tr><th>评分项</th><th>自动判定</th><th>人工 / 物理证据</th><th>当前结论</th></tr>${items.map(it => {
      const sp = specFor(it), v = verdict(runs.get(it.id) ?? [], sp?.runs ?? 3, layer);
      const how = it.metrics.map(m => m.how).filter(Boolean).join("；") || "—";
      return `<tr data-id="${esc(it.id)}" class="${cur?.id === it.id ? "on" : ""}"><td><b>${esc(it.id)}</b>${it.score != null ? ` · ${it.score} 分` : ""}<div class="hint">${esc(it.text.length > 28 ? it.text.slice(0, 28) + "…" : it.text)}</div></td>
        <td>${sp ? `accept <span class="mono">${esc(sp.name)}</span>` : `<span class="hint">没有 accept 规格</span>`}</td><td class="hint">${esc(how)}${saved.has(it.id) ? `<div class="mono">${esc(saved.get(it.id))}</div>` : ""}</td><td class="${v.cls}">${v.text}</td></tr>`;
    }).join("")}</table>`;
    $("sc-mat").querySelectorAll<HTMLElement>("tr[data-id]").forEach(tr => (tr.onclick = () => pick(tr.dataset.id!)));
  }
  function pick(id: string) {
    cur = items.find(x => x.id === id) ?? null; drawMat(); if (!cur) return;
    $("sc-item").hidden = false;
    $("sc-title").textContent = `${cur.id}：${cur.text}`;
    const sp = specFor(cur), all = specs();
    $<HTMLSelectElement>("sc-spec").innerHTML = all.map(s => `<option${s === sp ? " selected" : ""}>${esc(s.name)}</option>`).join("") || `<option value="">（app.yaml 没有 accept 规格）</option>`;
    $("sc-n").value = String(sp?.runs ?? 3);
    $("sc-dur").value = String(sp?.t_max_s ? Math.ceil(sp.t_max_s * 1.5) : 10);
    $<HTMLSelectElement>("sc-cf").innerHTML = plot.names.map(n => `<option>${esc(n)}</option>`).join("");
    drawRuns();
  }
  const spec = () => specs().find(s => s.name === $<HTMLSelectElement>("sc-spec").value) ?? null;
  function evalCap(t0: number, t1: number): Run {
    const cap = plot.capture(t0, t1 - t0), sp = spec();
    let r: AcceptR | null = null;
    if (sp) {
      const yi = plot.names.indexOf(sp.y), ri = yi >= 0 ? plot.refOf[yi] : -1;
      const tgt = cur?.metrics.find(m => m.accept === sp.name)?.value;
      if (yi >= 0) r = acceptEval(cap.rel, cap.ys[yi], ri >= 0 ? cap.ys[ri] : cap.rel.map(() => tgt ?? NaN), sp);
    }
    const n = (runs.get(cur!.id)?.length ?? 0) + 1;
    return { n, dur: t1 - t0, r, csv: csvOf(cap.rel, plot.names, cap.ys), png: snapRun(cap.rel, cap.ys, plot.names, plot.units, plot.refOf, plot.vis, `${cur!.id} 第 ${n} 轮（${(t1 - t0).toFixed(2)} s）`) };
  }
  function drawRuns() {
    if (!cur) return;
    const rs = runs.get(cur.id) ?? [], need = +$("sc-n").value || 3, v = verdict(rs, need, $<HTMLSelectElement>("sc-layer").value);
    $("sc-runs").innerHTML = rs.length ? `<table class="pf-tab"><tr><th>#</th><th>时长 s</th><th>到位用时 s</th><th>到位后误差</th><th>判定</th></tr>${rs.map(r => `<tr><td>${r.n}</td><td>${f2(r.dur)}</td><td>${f2(r.r?.total ?? NaN)}</td><td>${f2(r.r?.worst_err ?? NaN)}</td><td class="${r.r?.pass ? "ok" : "bad"}">${r.r ? (r.r.pass ? "通过" : esc(r.r.why)) : "无法判定（没选规格或通道不在）"}</td></tr>`).join("")}</table>
      <p>最差 ${need} 轮：<b class="${v.cls}">${v.text}</b>${v.w ? `；最慢 ${f2(v.w.total)} s，最大误差 ${f2(v.w.err)}` : ""}</p>` : `<p class="hint">还没跑。</p>`;
    $<HTMLButtonElement>("sc-save").disabled = !rs.length;
  }
  function stop() {
    if (!arm || !cur) return; clearInterval(arm.timer);
    if (arm.t0 != null) { const run = evalCap(arm.t0, plot.now()); runs.set(cur.id, [...(runs.get(cur.id) ?? []), run]); }
    arm = null; $("sc-state").textContent = ""; $("sc-go").textContent = "开始一轮"; drawRuns(); drawMat();
  }
  $("sc-go").onclick = () => {
    if (arm) return stop();
    if (!cur) return;
    const byCond = $<HTMLSelectElement>("sc-trig").value === "cond", dur = +$("sc-dur").value || 0;
    const fi = plot.names.indexOf($<HTMLSelectElement>("sc-cf").value), op = $<HTMLSelectElement>("sc-cop").value, x = +$("sc-cv").value;
    const last = () => { const y = plot.ys[fi]; return y?.length ? y[y.length - 1] : NaN; };
    arm = { t0: byCond ? null : plot.now(), timer: 0 };
    $("sc-go").textContent = "结束这一轮";
    $("sc-state").textContent = byCond ? `等待 ${plot.names[fi]} ${op} ${x}…` : "计时中…";
    arm.timer = window.setInterval(() => {
      if (!arm) return;
      if (arm.t0 == null) { if (condOk(last(), op, x)) { arm.t0 = plot.now(); $("sc-state").textContent = "条件成立，计时中…"; } return; }
      const el = plot.now() - arm.t0; $("sc-state").textContent = `计时 ${el.toFixed(1)} s`;
      if ((dur > 0 && el >= dur) || (byCond && !condOk(last(), op, x) && el > 0.2)) stop();
    }, 50);
  };
  $("sc-clear").onclick = () => { if (cur) { runs.delete(cur.id); drawRuns(); drawMat(); } };
  $("sc-save").onclick = async () => {
    if (!cur) return; const rs = runs.get(cur.id) ?? [], layer = $<HTMLSelectElement>("sc-layer").value, v = verdict(rs, +$("sc-n").value || 3, layer);
    const r = await call<any>("score_save", { code: code.replace(/[^A-Za-z0-9_-]/g, ""), item: cur.id.replace(/[^A-Za-z0-9_-]/g, ""), layer,
      summary: { verdict: v.text, result: v.w?.all ? "PASS" : "FAIL", worst: v.w ? `用时 ${f2(v.w.total)} s，误差 ${f2(v.w.err)}` : "—", spec: spec()?.name },
      runs: rs.map(x => ({ n: x.n, csv: x.csv, png_b64: x.png, result: x.r ? { pass: x.r.pass, total: x.r.total, worst_err: x.r.worst_err, why: x.r.why } : null, dur: x.dur })) }).catch(() => null);
    if (!r) return;
    saved.set(cur.id, r.dir); drawMat(); toast(`证据已存：${r.dir}（${r.files.length} 个文件）。requirements.yaml 的 evidence 可贴：${r.evidence}`, "ok");
  };
  $("sc-file").onchange = () => refresh($<HTMLSelectElement>("sc-file").value);
  $("sc-layer").onchange = () => { drawMat(); drawRuns(); };
  $("sc-n").oninput = drawRuns;
  $("sc-trig").onchange = () => { $("sc-condrow").hidden = $<HTMLSelectElement>("sc-trig").value !== "cond"; };
  return { refresh: () => refresh() };
}
