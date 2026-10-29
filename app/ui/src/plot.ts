// 曲线：每个可见通道一条 lane（small multiples，docs/26 P8），共享时间轴、光标同步。
// 量纲不同的通道各占一条 lane；标签列：色条、名称、实时值、每格刻度（/div，P9）。
// 叠加层（都画在 draw 钩子里，不进数据）：设定值虚线（schema ref_for 显式声明）、t0 阶跃锚点、A/B 光标与 Δ 带、上一轮余辉。
// 数据：环形缓冲（最多 32 s），按窗口跟随，按像素列 min/max 抽稀（尖峰不丢）。
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { minmax, windowSlice } from "./decimate";
import { niceDiv } from "./measure";

const KEEP_S = 32;
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const chColor = (i: number) => css(`--ch${(i % 8) + 1}`);
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
export const num = (v: number) => { const a = Math.abs(v); return a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : v.toFixed(3); };
const divs = new WeakMap<uPlot, number>();

type Lane = { i: number; r: number; u: uPlot; el: HTMLElement; rng: HTMLElement };
export type Ghost = { rel: number[]; ys: number[][]; label: string };

export class Plot {
  names: string[] = [];
  units: string[] = [];
  vis: boolean[] = [];
  refOf: number[] = [];          // refOf[i] = 画在 i 这条 lane 上的设定值通道，-1 没有
  t: number[] = [];
  ys: number[][] = [];
  win = 5;
  running = true;
  dirty = false;
  t0: number | null = null;      // 阶跃锚点（绝对时间）；有它时时间刻度相对 t0
  cur: [number | null, number | null] = [null, null];   // A/B 光标（绝对时间）
  ghost: Ghost | null = null;    // 余辉：上一轮相对 t0 的数据
  private lanes: Lane[] = [];
  private host: HTMLElement;
  private sync = uPlot.sync("dz-lanes");

  constructor(box: HTMLElement) {
    this.host = document.createElement("div");
    this.host.className = "lanes";
    box.prepend(this.host);
    new ResizeObserver(() => this.resize()).observe(this.host);
    const tick = () => { if (this.dirty && this.running) this.redraw(); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    window.addEventListener("dz-theme", () => { this.build(); this.dirty = true; });   // 颜色在创建时读出：换主题重建
  }

  // refFor[j] = j 是哪个通道的设定值（-1 不是）；被叠加的设定值不再单独占 lane
  setChannels(names: string[], units: string[], visible: boolean[], refFor: number[] = []) {
    this.names = names; this.units = units; this.vis = [...visible];
    this.refOf = names.map((_, i) => refFor.findIndex(r => r === i));
    this.t = []; this.ys = names.map(() => []); this.t0 = null; this.cur = [null, null]; this.ghost = null;
    this.build();
  }
  show(i: number, on: boolean) { this.vis[i] = on; this.build(); this.dirty = true; }
  last(i: number) { const a = this.ys[i]; return a?.length ? a[a.length - 1] : undefined; }
  clear() { this.t = []; this.ys = this.names.map(() => []); this.t0 = null; this.cur = [null, null]; this.dirty = true; }
  now() { return this.t.length ? this.t[this.t.length - 1] : 0; }
  laneIdx() { return this.lanes.map(l => l.i); }
  setCursor(k: 0 | 1, x: number | null) { this.cur[k] = x; this.repaint(); window.dispatchEvent(new Event("dz-cursor")); }
  setAnchor(x: number | null) { this.t0 = x; this.repaint(); }
  // 截取 [t0, t0+dur] 的数据，时间换成相对 t0（给历史 / 余辉用）
  capture(t0: number, dur: number): Ghost {
    const [a, b] = windowSlice(this.t, t0, t0 + dur);
    return { rel: this.t.slice(a, b).map(x => x - t0), ys: this.ys.map(y => y.slice(a, b)), label: "" };
  }
  private repaint() { this.dirty = true; if (!this.running) this.lanes.forEach(l => l.u.redraw(false)); }

  push(t: number[], y: Record<string, number[]>) {
    if (!t.length) return;
    if (this.t.length && t[0] < this.t[this.t.length - 1] - 1) this.clear();   // 板子复位：时间倒退
    this.t.push(...t);
    this.names.forEach((n, i) => this.ys[i].push(...(y[n] ?? t.map(() => NaN))));
    const cut = this.t.findIndex(x => x >= this.t[this.t.length - 1] - KEEP_S);
    if (cut > 0) { this.t.splice(0, cut); this.ys.forEach(a => a.splice(0, cut)); }
    this.dirty = true;
  }

  private laneSize(first: boolean) {
    const n = this.lanes.length || 1, r = this.host.getBoundingClientRect();
    const lab = parseFloat(css("--w-lab")) || 168, ruler = 24;
    const h = Math.floor((r.height - ruler) / n);
    return { width: Math.max(r.width - lab - 1, 100), height: Math.max(h + (first ? ruler : 0) - 1, 40) };
  }
  private resize() { this.lanes.forEach((l, k) => l.u.setSize(this.laneSize(k === 0))); }
  private xRef() { return this.t0 ?? this.now(); }
  xDiv() { return niceDiv(this.win, 10); }

  // 叠加层：Δ 带 → 余辉 → t0 → A/B 竖线（顺序决定遮挡）
  private overlay(u: uPlot, l: Lane, first: boolean) {
    const c = u.ctx, { left, top, width, height } = u.bbox, X = (x: number) => u.valToPos(x, "x", true);
    const inX = (p: number) => p >= left && p <= left + width;
    c.save(); c.beginPath(); c.rect(left, top, width, height); c.clip();
    const [A, B] = this.cur;
    if (A != null && B != null) { c.fillStyle = css("--acc-bg"); const a = X(Math.min(A, B)), b = X(Math.max(A, B)); c.fillRect(a, top, b - a, height); }
    const g = this.ghost;
    if (g && this.t0 != null && g.ys[l.i]?.length) {
      c.globalAlpha = .38; c.strokeStyle = chColor(l.i); c.lineWidth = devicePixelRatio; c.beginPath();
      let pen = false;
      g.rel.forEach((r, k) => { const v = g.ys[l.i][k]; if (Number.isNaN(v)) { pen = false; return; }
        const x = X(this.t0! + r), y = u.valToPos(v, "y", true); pen ? c.lineTo(x, y) : c.moveTo(x, y); pen = true; });
      c.stroke(); c.globalAlpha = 1;
    }
    const vline = (x: number, color: string, dash: number[], tag: string) => {
      const p = X(x); if (!inX(p)) return;
      c.strokeStyle = color; c.lineWidth = devicePixelRatio; c.setLineDash(dash.map(d => d * devicePixelRatio));
      c.beginPath(); c.moveTo(Math.round(p) + .5, top); c.lineTo(Math.round(p) + .5, top + height); c.stroke(); c.setLineDash([]);
      if (first) { c.fillStyle = color; c.font = `500 ${11 * devicePixelRatio}px ${css("--f-mono")}`; c.fillText(tag, p + 4 * devicePixelRatio, top + 12 * devicePixelRatio); }
    };
    if (this.t0 != null) vline(this.t0, css("--warn"), [3, 3], "t0");
    if (A != null) vline(A, css("--acc-t"), [], "A");
    if (B != null) vline(B, css("--acc-t"), [], "B");
    c.restore();
  }

  private build() {
    this.lanes.forEach(l => l.u.destroy());
    this.lanes = [];
    this.host.innerHTML = "";
    const isRef = new Set(this.refOf.filter(r => r >= 0));
    const idx = this.names.map((_, i) => i).filter(i => this.vis[i] && !isRef.has(i));
    const font = `400 11px ${css("--f-mono")}`;
    const grid = { stroke: css("--grid"), width: 1 }, tick = { show: false };
    idx.forEach(i => {
      const el = document.createElement("div"), r = this.refOf[i];
      el.className = "lane";
      el.style.setProperty("--c", chColor(i));   // 唯一的 inline：通道色绑定
      const ref = r >= 0 ? `<span class="lref" title="设定值（schema ref_for）">┄ ${esc(this.names[r])}</span>` : "";
      el.innerHTML = `<div class="lab"><b class="nm" title="${esc(this.names[i])}">${esc(this.names[i])}</b>
        <span class="lv mono" id="lv-${i}">—</span>${ref}<span class="lr mono" id="lr-${i}"></span></div><div class="lc"></div>`;
      this.host.append(el);
    });
    idx.forEach((i, k) => {
      const el = this.host.children[k] as HTMLElement, first = k === 0, r = this.refOf[i];
      const lane: Lane = { i, r, el, rng: el.querySelector(".lr")!, u: null as unknown as uPlot };
      this.lanes.push(lane);
      const series: uPlot.Series[] = [{}, { stroke: chColor(i), width: 1.5, points: { show: false } }];
      if (r >= 0 && this.vis[r]) series.push({ stroke: css("--setpoint"), width: 1, dash: [4, 3], points: { show: false } });
      const u = new uPlot({
        width: 100, height: 100,
        legend: { show: false },
        padding: [first ? 0 : 6, 28, 6, 0],     // 右侧留固定边距：首条的刻度字不会把它的绘图区挤得比其他 lane 窄（光标/锚点要对齐）
        cursor: { sync: { key: this.sync.key }, points: { size: 5 }, drag: { x: false, y: false } },
        scales: { x: { time: false }, y: { range: yRange } },
        axes: [
          { show: first, side: 0, size: 24, stroke: css("--muted"), grid, ticks: tick, font,
            splits: (_u, _a, lo, hi) => { const d = this.xDiv(), ref = this.xRef(), out: number[] = [];
              for (let x = ref + Math.ceil((lo - ref) / d) * d; x <= hi + 1e-9; x += d) out.push(x); return out; },
            values: (_u, v) => v.map(x => { const r = x - this.xRef(), n = Math.round(r / this.xDiv());
              return n % 2 ? "" : (this.t0 != null && r >= 0 ? "+" : "") + r.toFixed(this.xDiv() < .1 ? 2 : 1) + " s"; }) },
          { stroke: css("--muted"), grid, ticks: tick, font, size: 44, gap: 4,
            splits: (uu, _a, lo, hi) => { const d = divs.get(uu) ?? (hi - lo) / 4, out: number[] = [];
              for (let y = lo; y <= hi + d * 1e-6; y += d) out.push(y); return out; },
            // 首尾刻度不标数字：贴边的数字会被裁掉，读数看标签列的 /div
            values: (_u, v) => v.map((y, k) => k === 0 || k === v.length - 1 ? "" : num(Math.abs(y) < 1e-12 ? 0 : y)) },
        ],
        series,
        hooks: { draw: [uu => this.overlay(uu, lane, first)] },
      }, [[], [], ...(series.length > 2 ? [[]] : [])] as any, el.querySelector(".lc") as HTMLElement);
      // 单击放 A，Shift+单击放 B（Saleae / 示波器惯例），双击清除
      u.over.addEventListener("click", e => this.setCursor(e.shiftKey ? 1 : 0, u.posToVal(e.offsetX, "x")));
      u.over.addEventListener("dblclick", () => { this.cur = [null, null]; this.setCursor(0, null); });
      lane.u = u;
    });
    if (!idx.length && this.names.length) this.host.innerHTML = `<div class="empty-s">所有通道都已隐藏：在右侧“通道”里点开</div>`;
    requestAnimationFrame(() => { this.resize(); this.redraw(); });   // 暂停时换主题 / 开关通道也要有图
  }

  redraw() {
    if (!this.lanes.length) return;
    this.dirty = false;
    const tEnd = this.t.length ? this.t[this.t.length - 1] : this.win, t0 = tEnd - this.win;
    const [a, b] = windowSlice(this.t, t0, tEnd);
    const px = Math.round(this.lanes[0].u.bbox.width / devicePixelRatio) || 800;
    const [dt, dy] = minmax(this.t, this.ys, a, b, t0, tEnd, px);
    for (const l of this.lanes) {
      const data: any[] = [dt, dy[l.i]];
      if (l.u.series.length > 2) data.push(dy[l.r]);
      l.u.batch(() => { l.u.setData(data, false); l.u.setScale("x", { min: t0, max: tEnd }); });
      const d = divs.get(l.u);
      if (d) l.rng.textContent = `${num(d)}${this.units[l.i] ? " " + this.units[l.i] : ""}/div`;
    }
  }
}

// Y 轴跟数据走：上下各留 8%，再对齐到 1/2/5 的每格刻度（约 4 格）；数据几乎是平的时给最小跨度
export function yRange(u: uPlot, lo: number | null, hi: number | null): [number, number] {
  if (lo == null || hi == null || !isFinite(lo) || !isFinite(hi)) { lo = -1; hi = 1; }
  const mid = (lo + hi) / 2, minSpan = Math.max(Math.abs(mid) * 0.1, 2);
  let span = hi - lo;
  if (span < minSpan) { lo = mid - minSpan / 2; hi = mid + minSpan / 2; span = minSpan; }
  const d = niceDiv(span * 1.16, 4);
  if (u) divs.set(u, d);
  return [Math.floor((lo - span * .08) / d) * d, Math.ceil((hi + span * .08) / d) * d];
}
