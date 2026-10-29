// 验收判定（纯函数，可单测；侧车 dzbench/accept.py 是同一定义的 Python 版，两边测试用同一组数据）。
// 评委看的不是超调/调节时间，而是“到位”：|误差| ≤ band 且 |速度| ≤ vmax，连续保持 hold_s。
// 规格来自 schema 的 accept（yaml link.accept），全是物理单位（字段写了 cal 就是标定后的单位），界面不认题目。
//   段：设定值每变一次（连续变化的斜坡算一次）开一段；窗口内设定值没变 = 一段“保持”任务（从窗口开头算）。
//   到位时刻 = 进入并保持满 hold_s 的那一刻（= 秒表能确认的时刻，偏保守），从该段起点计。
//   到位后最大误差 = 进入那一刻起到本段结束的 max|e|（全程误差要求按这个看）。
//   通过 = 每段都到位 && 到位后误差 ≤ band && （有 t_max_s 时）从第一段起点到最后一段到位 ≤ t_max_s。
//   速度 = 100 ms 窗口差分（相机/编码器量化噪声下比逐点差分稳；窗口不足时用已有样本）。
export type AcceptSpec = { name?: string; y: string; band: number; vmax?: number; hold_s?: number; t_max_s?: number; runs?: number };
export type Seg = { t0: number; target: number; arrived: boolean; t_arrive: number; err_after: number };
export type AcceptR = { pass: boolean; segs: Seg[]; total: number; worst_err: number; why: string };

export const V_WIN = 0.1;

export function acceptEval(t: number[], y: number[], sp: number[], a: AcceptSpec): AcceptR | null {
  const n = Math.min(t.length, y.length, sp.length);
  if (n < 2) return null;
  const hold = a.hold_s ?? 0.3, vmax = a.vmax ?? Infinity, tol = a.band * 1e-3;
  const starts = [0];
  const ch = (k: number) => k >= 1 && Math.abs(sp[k] - sp[k - 1]) > tol;
  for (let k = 1; k < n; k++) if (ch(k) && !ch(k - 1)) starts.push(k);
  if (starts.length > 1) starts.shift();              // 有变化：第一次变化之前那段不算（还没开始）
  const v = (k: number) => { let j = k; while (j > 0 && t[k] - t[j - 1] <= V_WIN + 1e-9) j--; return j === k ? 0 : (y[k] - y[j]) / (t[k] - t[j]); };
  const segs: Seg[] = starts.map((s, i) => {
    const e = i + 1 < starts.length ? starts[i + 1] : n, target = sp[e - 1];
    let entry = -1, arrive = -1;
    for (let k = s; k < e; k++) {
      const ok = Math.abs(y[k] - sp[k]) <= a.band && Math.abs(v(k)) <= vmax;
      if (!ok) { entry = -1; continue; }
      if (entry < 0) entry = k;
      if (t[k] - t[entry] >= hold - 1e-9) { arrive = k; break; }
    }
    let err = NaN;
    if (arrive >= 0) { err = 0; for (let k = entry; k < e; k++) err = Math.max(err, Math.abs(y[k] - sp[k])); }
    return { t0: t[s], target, arrived: arrive >= 0, t_arrive: arrive >= 0 ? t[arrive] - t[s] : NaN, err_after: err };
  });
  const last = segs[segs.length - 1], allIn = segs.every(s => s.arrived);
  const total = allIn ? last.t0 + last.t_arrive - segs[0].t0 : NaN;
  const worst = allIn ? Math.max(...segs.map(s => s.err_after)) : NaN;
  const bad = segs.findIndex(s => !s.arrived);
  const why = bad >= 0 ? `第 ${bad + 1} 段（→${+segs[bad].target.toPrecision(4)}）没到位` : worst > a.band ? `到位后误差 ${+worst.toPrecision(3)} 超出 ±${a.band}`
    : a.t_max_s != null && total > a.t_max_s ? `用时 ${total.toFixed(2)} s 超过 ${a.t_max_s} s` : "";
  return { pass: !why, segs, total, worst_err: worst, why };
}

// 最近 N 轮按最差一轮判（评委：连续 N 次，以最差的那次为准）
export function worstOf(rs: (AcceptR | null)[], n: number) {
  const r = rs.slice(0, n).filter((x): x is AcceptR => !!x);
  if (!r.length) return null;
  const fin = (xs: number[]) => xs.some(x => !Number.isFinite(x)) ? NaN : Math.max(...xs);
  return { n: r.length, need: n, pass: r.filter(x => x.pass).length, all: r.length >= n && r.every(x => x.pass), total: fin(r.map(x => x.total)), err: fin(r.map(x => x.worst_err)) };
}
