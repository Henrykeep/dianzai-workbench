// 曲线：每个可见通道一条 lane（small multiples，docs/26 P8），共享时间轴、光标同步。
// 量纲不同的通道不再挤在一根 Y 轴上；每条 lane 左侧是标签列：色条、名称、实时值、当前量程（P9）。
// 数据：环形缓冲（最多 32 s），按窗口跟随，按像素列 min/max 抽稀（尖峰不丢）。
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { minmax, windowSlice } from "./decimate";

const KEEP_S = 32;
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const chColor = (i: number) => css(`--ch${(i % 8) + 1}`);
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
export const num = (v: number) => { const a = Math.abs(v); return a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : v.toFixed(3); };

type Lane = { i: number; u: uPlot; el: HTMLElement; rng: HTMLElement };

export class Plot {
  names: string[] = [];
  units: string[] = [];
  vis: boolean[] = [];
  t: number[] = [];
  ys: number[][] = [];
  win = 5;
  running = true;
  dirty = false;
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

  setChannels(names: string[], units: string[], visible: boolean[]) {
    this.names = names; this.units = units; this.vis = [...visible];
    this.t = []; this.ys = names.map(() => []);
    this.build();
  }
  show(i: number, on: boolean) { this.vis[i] = on; this.build(); this.dirty = true; }
  last(i: number) { const a = this.ys[i]; return a?.length ? a[a.length - 1] : undefined; }
  clear() { this.t = []; this.ys = this.names.map(() => []); this.dirty = true; }

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

  private build() {
    this.lanes.forEach(l => l.u.destroy());
    this.lanes = [];
    this.host.innerHTML = "";
    const idx = this.names.map((_, i) => i).filter(i => this.vis[i]);
    const font = `400 11px ${css("--f-mono")}`;
    const grid = { stroke: css("--grid"), width: 1 }, tick = { show: false };
    idx.forEach(i => {
      const el = document.createElement("div");
      el.className = "lane";
      el.style.setProperty("--c", chColor(i));   // 唯一的 inline：通道色绑定
      el.innerHTML = `<div class="lab"><div class="lh"><b class="nm">${esc(this.names[i])}</b><span class="lv mono" id="lv-${i}">—</span></div>
        <span class="lr mono" id="lr-${i}"></span></div><div class="lc"></div>`;
      this.host.append(el);
    });
    idx.forEach((i, k) => {
      const el = this.host.children[k] as HTMLElement, first = k === 0;
      this.lanes.push({ i, el, rng: el.querySelector(".lr")!, u: null as unknown as uPlot });
      const u = new uPlot({
        width: 100, height: 100,
        legend: { show: false },
        cursor: { sync: { key: this.sync.key }, points: { size: 5 }, drag: { x: true, y: false } },
        scales: { x: { time: false }, y: { range: yRange } },
        axes: [
          { show: first, side: 0, size: 24, stroke: css("--muted"), grid, ticks: tick, font, values: (_u, v) => v.map(x => (x - (this.t.at(-1) ?? 0)).toFixed(1) + " s") },
          { stroke: css("--muted"), grid, ticks: tick, font, size: 44, gap: 4, splits: (_u, _a, lo, hi) => [lo, (lo + hi) / 2, hi], values: (_u, v) => v.map(num) },
        ],
        series: [{}, { stroke: chColor(i), width: 1.5, points: { show: false } }],
      }, [[], []], el.querySelector(".lc") as HTMLElement);
      this.lanes[k].u = u;
    });
    if (!idx.length && this.names.length) this.host.innerHTML = `<div class="empty-s">所有通道都已隐藏：在右侧“通道”里点开</div>`;
    requestAnimationFrame(() => this.resize());
  }

  redraw() {
    if (!this.lanes.length) return;
    this.dirty = false;
    const tEnd = this.t.length ? this.t[this.t.length - 1] : this.win, t0 = tEnd - this.win;
    const [a, b] = windowSlice(this.t, t0, tEnd);
    const px = Math.round(this.lanes[0].u.bbox.width / devicePixelRatio) || 800;
    const [dt, dy] = minmax(this.t, this.ys, a, b, t0, tEnd, px);
    for (const l of this.lanes) {
      l.u.batch(() => { l.u.setData([dt, dy[l.i]] as any, false); l.u.setScale("x", { min: t0, max: tEnd }); });
      const s = l.u.scales.y;
      if (s.min != null && s.max != null) l.rng.textContent = `${num(s.min)} … ${num(s.max)}${this.units[l.i] ? " " + this.units[l.i] : ""}`;
    }
  }
}

// Y 轴跟数据走：上下各留 8%；数据几乎是平的时给一个最小跨度（按量级取，0 附近 ±1）
export function yRange(_u: uPlot, lo: number | null, hi: number | null): [number, number] {
  if (lo == null || hi == null || !isFinite(lo) || !isFinite(hi)) return [-1, 1];
  const mid = (lo + hi) / 2, minSpan = Math.max(Math.abs(mid) * 0.1, 2);
  let span = hi - lo;
  if (span < minSpan) { lo = mid - minSpan / 2; hi = mid + minSpan / 2; span = minSpan; }
  return [lo - span * 0.08, hi + span * 0.08];
}
