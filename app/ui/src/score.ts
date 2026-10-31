// 评分页（产品逻辑重组 · 评分页）：评分项来自 requirements.yaml，判定用 app.yaml 的 accept 规格（accept.ts，与侧车 accept.py 同一定义）。
// 每项跑 N 轮：开始 / 结束用按钮，或用遥测条件（如 run > 0.5 开始、跑满 X 秒或条件不再成立结束）；每轮自动计时、判到位，N 轮按最差一轮判。
// 证据：每轮 CSV + 曲线截图 + result.json，经侧车 score_save 存到 docs/verify/<题号>/logs/（目录由 tools/req.py newlog 建）。
// 表格结构借 DS-land-and-air《D题 V23 联调与计分矩阵》的“得分验收矩阵”：评分项 | 自动判定 | 人工 / 物理证据 | 当前结论（默认未验收）。
import { acceptEval, worstOf, type AcceptSpec, type AcceptR } from "./accept";
import type { Plot } from "./plot";
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
type Call = <T = any>(op: string, a?: Record<string, unknown>) => Promise<T>;
type Metric = { name: string; op?: string; value?: number; unit?: string; how?: string; accept?: string; test_id?: string };
export type ScoreItem = { id: string; part?: string; score?: number; text: string; metrics: Metric[]; evidence: unknown[]; accept?: string; runs?: number };
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
  g.fillStyle = css("--surface-1"); g.fillRect(0, 0, W, H); g.font = "13px sans-serif"; g.fillStyle = css("--text-primary"); g.fillText(title, 8, 18);
  const t0 = rel[0], t1 = rel[rel.length - 1], X = (t: number) => PADL + (t - t0) / (t1 - t0 || 1) * (W - PADL - PADR);
  L.forEach((ln, k) => {
    const y0 = TOP + k * LH, ser = [ys[ln.y], ln.ref >= 0 ? ys[ln.ref] : []];
    const all = ser.flat().filter(Number.isFinite); let lo = Math.min(...all), hi = Math.max(...all);
    if (!all.length) { lo = -1; hi = 1; } if (hi - lo < 1e-9) { lo -= 1; hi += 1; } const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const Y = (v: number) => y0 + 8 + (hi - v) / (hi - lo) * (LH - 24);
    g.strokeStyle = css("--border"); g.strokeRect(PADL, y0 + 8, W - PADL - PADR, LH - 24);
    g.fillStyle = css("--text-muted"); g.font = "12px monospace"; g.fillText(hi.toPrecision(3), 4, y0 + 18); g.fillText(lo.toPrecision(3), 4, y0 + LH - 18);
    ser.forEach((a, si) => { if (!a.length) return; g.strokeStyle = si ? css("--ch2") : css("--ch1"); g.setLineDash(si ? [5, 4] : []); g.beginPath();
      let pen = false; rel.forEach((t, q) => { const v = a[q]; if (!Number.isFinite(v)) { pen = false; return; } pen ? g.lineTo(X(t), Y(v)) : g.moveTo(X(t), Y(v)); pen = true; }); g.stroke(); });
    g.setLineDash([]); g.font = "12px sans-serif"; g.fillStyle = css("--ch1");
    g.fillText(`${names[ln.y]}${units[ln.y] ? ` (${units[ln.y]})` : ""}`, PADL + 6, y0 + 22);
    if (ln.ref >= 0) { g.fillStyle = css("--ch2"); g.fillText(`- - ${names[ln.ref]}`, PADL + 6, y0 + 38); }
  });
  g.fillStyle = css("--text-muted"); g.font = "12px monospace";
  for (let q = 0; q <= 5; q++) { const t = t0 + (t1 - t0) * q / 5; g.fillText(t.toFixed(2) + " s", X(t) - 18, H - 8); }
  return o.toDataURL("image/png");
}

export function initScore(call: Call, plot: Plot, specs: () => AcceptSpec[], toast: (t: string, k?: "ok" | "warn") => void) {
  const root = document.getElementById("score"); if (!root) return { refresh() {} };
  let items: ScoreItem[] = [], code = "", reqPath = "", cur: ScoreItem | null = null;
  const runs = new Map<string, Run[]>(), saved = new Map<string, string>(), last = new Map<string, { dir: string; layer: string; result: string; note: string }>();
  let arm: null | { t0: number | null; timer: number } = null;
  const $ = <T extends HTMLElement = HTMLInputElement>(id: string) => document.getElementById(id) as unknown as T;

  async function refresh(path?: string) {
    const r = await call<any>("score_items", path ? { path } : {}).catch(() => null);
    if (!r) { $("sc-mat").innerHTML = `<p class="hint">读不到评分项：先在项目页第 ① 步读题。</p>`; return; }
    items = r.items; code = r.code; reqPath = r.path; if (cur) cur = items.find(x => x.id === cur!.id) ?? null;
    $<HTMLSelectElement>("sc-file").innerHTML = (r.candidates as string[]).map(c => `<option${c === r.path ? " selected" : ""}>${esc(c)}</option>`).join("") || `<option>${esc(r.path)}</option>`;
    if (cur && !arm) pick(cur.id); else drawMat();
  }
  const specFor = (it: ScoreItem) => { const nm = it.accept ?? it.metrics.find(m => m.accept)?.accept; return specs().find(s => s.name === nm) ?? null; };
  function drawMat() {
    const layer = $<HTMLSelectElement>("sc-layer").value;
    // 列表而非四列表格：侧栏窄，只留“哪一项 · 几分 · 结论”，判定方式和证据放 title 与选中项详情
    const tot = items.reduce((a, it) => a + (it.score ?? 0), 0);
    const got = items.reduce((a, it) => { const sp = specFor(it); return a + (verdict(runs.get(it.id) ?? [], sp?.runs ?? 3, layer).cls === "ok" ? (it.score ?? 0) : 0); }, 0);
    const auto = items.filter(it => specFor(it)).length;
    $("sc-mat").innerHTML = `<div class="sc-sum"><div><b class="mono">${got}</b><span class="mono"> / ${tot} 分已通过</span></div><span>${items.filter(it => !(runs.get(it.id) ?? []).length && !saved.has(it.id)).length} 项还没有测试记录（按 0 分计）· ${auto} 项可自动判</span><div class="bar"><i style="width:${tot ? (got / tot) * 100 : 0}%"></i></div></div><div class="sc-head"><span>评分项</span><span>结论</span></div><ul class="sc-mat">${items.map(it => {
      const sp = specFor(it), v = verdict(runs.get(it.id) ?? [], sp?.runs ?? 3, layer);
      const how = it.metrics.map(m => m.how).filter(Boolean).join("；") || "—";
      const tip = `自动判定：${sp ? "accept " + sp.name : "没有 accept 规格"}\n人工 / 物理证据：${how}${saved.has(it.id) ? "\n证据：" + saved.get(it.id) : ""}`;
      return `<li data-id="${esc(it.id)}" class="${cur?.id === it.id ? "on" : ""}" title="${esc(tip)}"><div class="sc-l"><div class="sc-id"><b>${esc(it.id)}</b>${it.score != null ? `<span class="sc-pt mono">${it.score} 分</span>` : ""}${sp ? `<span class="sc-auto">可自动判</span>` : ""}</div><div class="sc-tx">${esc(it.text)}</div></div>${(runs.get(it.id) ?? []).length || saved.has(it.id) ? `<span class="sc-v ${v.cls}">${v.text}</span>` : `<span class="sc-v none" title="测评时没有记录的项按 0 分计：先跑一轮留数据">无记录 · 计 0 分</span>`}</li>`;
    }).join("")}</ul>`;
    $("sc-mat").querySelectorAll<HTMLElement>("li[data-id]").forEach(tr => (tr.onclick = () => pick(tr.dataset.id!)));
  }
  function pick(id: string) {
    cur = items.find(x => x.id === id) ?? null; drawMat(); if (!cur) return;
    $("sc-item").hidden = false;
    $("sc-title").textContent = `${cur.id}：${cur.text}`;
    const sp = specFor(cur), all = specs();
    $<HTMLSelectElement>("sc-spec").innerHTML = all.map(s => `<option${s === sp ? " selected" : ""}>${esc(s.name)}</option>`).join("") || `<option value="">（app.yaml 没有 accept 规格）</option>`;
    $("sc-n").value = String(cur.runs ?? sp?.runs ?? 3);
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
    $<HTMLButtonElement>("sc-save").disabled = !rs.length; $<HTMLButtonElement>("sc-wb").disabled = !last.has(cur.id); $("sc-wbbox").hidden = true;
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
    saved.set(cur.id, r.dir); last.set(cur.id, { dir: r.dir, layer, result: v.w?.all ? "pass" : v.w && v.w.pass ? "partial" : "fail", note: `工作台评分页：${v.text}；${v.w ? `最慢 ${f2(v.w.total)} s，最大误差 ${f2(v.w.err)}` : ""}；规格 ${spec()?.name ?? "—"}` });
    $<HTMLButtonElement>("sc-wb").disabled = false; drawMat(); toast(`证据已存：${r.dir}（${r.files.length} 个文件）。requirements.yaml 的 evidence 可贴：${r.evidence}`, "ok");
  };
  // 写回 requirements.yaml：先给 diff，确认才写（文件在预览后被改过就拒绝）
  $("sc-wb").onclick = async () => {
    if (!cur || !last.has(cur.id)) return; const a = { path: reqPath, item: cur.id, ...last.get(cur.id)! }, box = $("sc-wbbox");
    const pv = await call<any>("score_writeback", a).catch(() => null); if (!pv) return;
    box.hidden = false; box.innerHTML = `<p class="hint">将在 ${esc(pv.path)} 的 ${esc(cur.id)} 下加一条 evidence（只加这一行，注释和排版不动）：</p><pre class="mono pf-pre">${esc(pv.diff)}</pre>`;
    const b = document.createElement("button"); b.className = "btn pri"; b.type = "button"; b.textContent = "确认写回";
    b.onclick = async () => { b.disabled = true; const w = await call<any>("score_writeback", { ...a, confirm: true, sha: pv.sha }).catch(() => null);
      if (w) { box.innerHTML = `<p class="hint">已写回 ${esc(w.path)}。</p>`; toast(`已写回 ${w.path}（${cur!.id}）`, "ok"); refresh(reqPath); } else b.disabled = false; };
    box.append(b);
  };
  $("sc-file").onchange = () => refresh($<HTMLSelectElement>("sc-file").value);
  $("sc-layer").onchange = () => { drawMat(); drawRuns(); };
  $("sc-n").oninput = drawRuns;
  $("sc-trig").onchange = () => { $("sc-condrow").hidden = $<HTMLSelectElement>("sc-trig").value !== "cond"; };
  return { refresh: () => refresh() };
}
