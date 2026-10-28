// uPlot 封装：环形缓冲（最多 30 s），按窗口跟随；SerialPlot/VOFA+ 式“开箱即看”，PlotJuggler 式通道开关
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

const KEEP_S = 32;
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const chColor = (i: number) => css(`--ch${(i % 8) + 1}`);

export class Plot {
  u?: uPlot;
  names: string[] = [];
  t: number[] = [];
  ys: number[][] = [];
  win = 5;
  running = true;
  dirty = false;

  constructor(private box: HTMLElement) {
    new ResizeObserver(() => this.u?.setSize(this.size())).observe(box);
    const tick = () => { if (this.dirty && this.running) this.redraw(); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }

  private size() { const r = this.box.getBoundingClientRect(); return { width: Math.max(r.width - 16, 100), height: Math.max(r.height - 8, 100) }; }

  setChannels(names: string[], units: string[], visible: boolean[]) {
    this.u?.destroy();
    this.names = names; this.t = []; this.ys = names.map(() => []);
    const grid = { stroke: css("--grid-2"), width: 1 };
    const ax = { stroke: css("--dim"), grid, ticks: { stroke: css("--grid-2"), width: 1 }, font: "500 10px JetBrains Mono", };
    this.u = new uPlot({
      ...this.size(),
      legend: { show: false },
      cursor: { points: { size: 6 }, drag: { x: true, y: false } },
      scales: { x: { time: false } },
      axes: [{ ...ax, values: (_u, v) => v.map(x => x.toFixed(1) + " s") }, { ...ax, size: 56 }],
      series: [{}, ...names.map((n, i) => ({ label: n, stroke: chColor(i), width: i === 0 ? 1.75 : 1.25, show: visible[i], dash: i >= 4 ? [6, 2, 1, 2] : undefined, value: (_u: uPlot, v: number | null) => v == null ? "—" : v.toFixed(3) + (units[i] ? " " + units[i] : "") }))],
    }, [[], ...names.map(() => [])], this.box);
  }

  push(t: number[], y: Record<string, number[]>) {
    if (!t.length) return;
    if (this.t.length && t[0] < this.t[this.t.length - 1] - 1) this.clear();   // 板子复位：时间倒退
    this.t.push(...t);
    this.names.forEach((n, i) => this.ys[i].push(...(y[n] ?? t.map(() => NaN))));
    const cut = this.t.findIndex(x => x >= this.t[this.t.length - 1] - KEEP_S);
    if (cut > 0) { this.t.splice(0, cut); this.ys.forEach(a => a.splice(0, cut)); }
    this.dirty = true;
  }

  clear() { this.t = []; this.ys = this.names.map(() => []); this.dirty = true; }

  redraw() {
    if (!this.u) return;
    this.dirty = false;
    const tEnd = this.t.length ? this.t[this.t.length - 1] : this.win;
    this.u.batch(() => {
      this.u!.setData([this.t, ...this.ys] as any, false);
      this.u!.setScale("x", { min: tEnd - this.win, max: tEnd });
    });
  }

  show(i: number, on: boolean) { this.u?.setSeries(i + 1, { show: on }); }
  last(i: number) { const a = this.ys[i]; return a?.length ? a[a.length - 1] : undefined; }
}
