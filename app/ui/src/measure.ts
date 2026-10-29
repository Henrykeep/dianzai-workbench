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
