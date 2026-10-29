// A/B 光标测量（纯函数，可单测）：按时间找最近样本，区间内求 min/max/均值。
// 参考 Saleae Logic 2 / 示波器的 Δ 读数：Δt、1/Δt、每通道 A、B、Δ。
export type MRow = { i: number; a: number; b: number; d: number; min: number; max: number; mean: number };

export function nearest(t: number[], x: number): number {
  let lo = 0, hi = t.length - 1;
  if (hi < 0) return -1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] < x) lo = m + 1; else hi = m; }
  return lo > 0 && Math.abs(t[lo - 1] - x) <= Math.abs(t[lo] - x) ? lo - 1 : lo;
}

export function measure(t: number[], ys: number[][], ta: number, tb: number, idx: number[]): MRow[] {
  const ia = nearest(t, Math.min(ta, tb)), ib = nearest(t, Math.max(ta, tb));
  if (ia < 0) return [];
  const flip = ta > tb;
  return idx.map(i => {
    const y = ys[i]; let min = Infinity, max = -Infinity, s = 0, n = 0;
    for (let k = ia; k <= ib; k++) { const v = y[k]; if (Number.isNaN(v)) continue; min = Math.min(min, v); max = Math.max(max, v); s += v; n++; }
    const a = y[flip ? ib : ia], b = y[flip ? ia : ib];
    return { i, a, b, d: b - a, min: n ? min : NaN, max: n ? max : NaN, mean: n ? s / n : NaN };
  });
}

// 刻度：把一个跨度分成 n 格，每格取 1/2/5×10^k（示波器的 /div 档位）
export function niceDiv(span: number, n: number): number {
  const raw = span / n, p = 10 ** Math.floor(Math.log10(raw || 1)), m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

// 阶跃指标（纯函数，可单测）：逐行移植侧车 dzbench/agent/tuning.py 的 find_step + step_metrics，
// 保证界面读数和“分析阶跃”/调参护栏用的是同一个定义（同一组数据两边结果一致，见 tests/measure.test.ts）。
// 起点 = 设定值最后一次变化（阶跃或斜坡）的开始；y0 = 起点前一个样本；目标 = 设定值末值；
// 超调按阶跃方向；tr = 10%→90%；ts = 最后一次离开 ±band 之后的第一个样本；ess = 末值误差（% 幅度）。
export type StepM = { Mp: number; tr: number; ts: number; ess: number; settled: boolean; t0: number };
export function findStep(sp: number[], tol = 0.01): number | null {
  const n = sp.length, fin = sp[n - 1];
  let lo = Infinity, hi = -Infinity; for (const v of sp) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const span = hi - lo; if (!(span > 1e-9)) return null;
  let i = -1; for (let k = n - 1; k >= 0; k--) if (Math.abs(sp[k] - fin) > tol * span) { i = k; break; }
  if (i < 0) return null;
  while (i > 0 && Math.abs(sp[i] - sp[i - 1]) > 1e-9) i--;
  return i + 1 < n ? Math.max(i, 1) : null;
}
export function stepMetrics(t: number[], y: number[], sp: number[], band = .05): StepM | null {
  const n = Math.min(t.length, y.length, sp.length);
  if (n < 10) return null;
  t = t.slice(0, n); y = y.slice(0, n); sp = sp.slice(0, n);
  const i0 = findStep(sp); if (i0 == null) return null;
  const t0 = t[i0], y0 = y[i0 - 1], r = sp[n - 1], amp = r - y0;
  if (!(Math.abs(amp) > 1e-9) || t[n - 1] - t0 < .2) return null;
  const ys: number[] = [], ts: number[] = [];
  for (let k = i0; k < n; k++) { ys.push((y[k] - y0) / amp); ts.push(t[k] - t0); }
  const t10 = ts[ys.findIndex(v => v >= .1)], t90 = ts[ys.findIndex(v => v >= .9)];
  let last = -1; ys.forEach((v, k) => { if (Math.abs(v - 1) > band) last = k; });
  const settled = last + 1 < ys.length;
  return { t0, Mp: Math.max(0, (Math.max(...ys) - 1) * 100), tr: t10 != null && t90 != null ? t90 - t10 : NaN,
    ts: last < 0 ? 0 : settled ? ts[last + 1] : NaN, ess: Math.abs(1 - ys[ys.length - 1]) * 100, settled };
}
