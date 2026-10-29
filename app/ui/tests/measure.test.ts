import { nearest, measure, niceDiv, stepMetrics } from "../src/measure.ts";
const t = [0, 1, 2, 3, 4], y = [0, 2, 4, 6, 8];
if (nearest(t, 2.4) !== 2 || nearest(t, 2.6) !== 3) throw "nearest";
const m = measure(t, [y], 1, 3, [0])[0]; if (m.d !== 4 || m.mean !== 4) throw "measure";
if (niceDiv(10, 10) !== 1 || niceDiv(7, 10) !== 1 || niceDiv(1.3, 10) !== 0.2) throw "niceDiv";
// 二阶系统 wn=9.5 zeta=.46 → Mp≈19.5%（与 v6 示意稿同一仿真）
const T: number[] = [], Y: number[] = [], R: number[] = []; let x = 0, v = 0;
for (let k = 0; k <= 1600; k++) { const tt = k * .001; T.push(tt); Y.push(x); R.push(k < 50 ? 0 : 30); const a = 90.25 * (R[k] - x) - 2 * .46 * 9.5 * v; v += a * .001; x += v * .001; }
const s = stepMetrics(T, Y, R)!;
if (Math.abs(s.Mp - 19.5) > 0.8 || s.tr < .14 || s.tr > .2 || s.ts < .4 || s.ts > .7 || !s.settled) throw "step " + JSON.stringify(s);
const d = stepMetrics(T, Y.map(q => -q), R.map(q => -q))!; if (Math.abs(d.Mp - s.Mp) > 1e-9) throw "step down";
if (stepMetrics(T, Y, T.map(() => 30)) !== null) throw "no step in sp";
console.log("measure ok", s.Mp.toFixed(1), s.tr.toFixed(3), s.ts.toFixed(2));
