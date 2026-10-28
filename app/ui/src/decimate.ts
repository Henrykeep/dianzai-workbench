// 每像素 min/max 抽稀：窗口内点数远多于像素时，每个像素列只保留该列的最小值和最大值（按出现顺序），
// 尖峰不会丢、毛刺不会被平均掉；点数少时原样返回。时间轴必须单调递增。
export function windowSlice(t: number[], t0: number, t1: number): [number, number] {
  let lo = 0, hi = t.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] < t0) lo = m + 1; else hi = m; }
  const a = Math.max(lo - 1, 0);                    // 多留一个点，线从左边界外接进来
  lo = a; hi = t.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] <= t1) lo = m + 1; else hi = m; }
  return [a, Math.min(lo + 1, t.length)];
}

export function minmax(t: number[], ys: number[][], a: number, b: number, t0: number, t1: number, px: number): [number[], number[][]] {
  const n = b - a;
  if (n <= px * 2 || px < 1) return [t.slice(a, b), ys.map(y => y.slice(a, b))];
  const span = (t1 - t0) || 1;
  // 所有通道共用时间轴：每列输出两个时刻（列内最早、最晚样本），各通道在这两个时刻放 min/max（先出现的放前面）
  const ot: number[] = [], oy: number[][] = ys.map(() => []);
  let i = a;
  while (i < b) {
    const col = Math.floor((t[i] - t0) / span * px);
    let j = i;
    while (j < b && Math.floor((t[j] - t0) / span * px) === col) j++;
    if (j - i <= 2) { for (let k = i; k < j; k++) { ot.push(t[k]); ys.forEach((y, c) => oy[c].push(y[k])); } }
    else {
      ot.push(t[i], t[j - 1]);
      ys.forEach((y, c) => {
        let mn = Infinity, mx = -Infinity, imn = i, imx = i;
        for (let k = i; k < j; k++) { const v = y[k]; if (v < mn) { mn = v; imn = k; } if (v > mx) { mx = v; imx = k; } }
        if (mn === Infinity) { oy[c].push(NaN, NaN); return; }          // 整列都是 NaN
        if (imn <= imx) oy[c].push(mn, mx); else oy[c].push(mx, mn);
      });
    }
    i = j;
  }
  return [ot, oy];
}
