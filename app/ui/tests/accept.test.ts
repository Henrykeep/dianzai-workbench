import { acceptEval, worstOf } from "../src/accept.ts";
import { calFn, calMap } from "../src/calib.ts";
import { readFileSync } from "node:fs";
// 同一组数据 Python 侧（app/sidecar/tests/test_accept.py）也跑，期望值写在 JSON 里，两边定义不一致就有一边挂
const V = JSON.parse(readFileSync("../sidecar/tests/accept_vectors.json", "utf8"));
for (const c of V.cases) {
  const r = acceptEval(c.t, c.y, c.sp, c.spec)!, x = c.expect;
  const near = (a: number, b: number | null) => b == null ? !Number.isFinite(a) : Math.abs(a - b) < 1e-6;
  if (r.pass !== x.pass || r.segs.length !== x.segs || !near(r.total, x.total) || !near(r.worst_err, x.worst_err))
    throw `accept ${c.name}: ${JSON.stringify({ pass: r.pass, segs: r.segs.length, total: r.total, worst_err: r.worst_err, why: r.why })}`;
}
const w = worstOf([acceptEval([0, 1], [0, 0], [0, 0], { y: "y", band: 1, hold_s: 0.5 })], 3)!;
if (w.all || w.n !== 1 || w.pass !== 1) throw "worstOf needs N runs";
// 标定：两点直线、多点最小二乘、分段；设定值继承被控量的 cal
const l = calFn({ unit: "cm", pts: [[0, 0], [600, 100]] }); if (Math.abs(l(30) - 5) > 1e-9) throw "cal linear";
const q = calFn({ unit: "cm", pts: [[0, 0], [1, 1.1], [2, 1.9], [3, 3]] }); if (Math.abs(q(3) - 2.97) > 1e-9) throw "cal lsq " + q(3);
const pw = calFn({ unit: "cm", mode: "piecewise", pts: [[0, 0], [10, 1], [20, 3]] }); if (pw(15) !== 2 || pw(-10) !== -1 || pw(30) !== 5) throw "cal pw";
const m = calMap([{ name: "x", cal: { unit: "cm", pts: [[0, 0], [6, 1]] } }, { name: "sp", ref_for: "x" }, { name: "z" }]);
if (m.get("sp")?.unit !== "cm" || m.has("z") || m.get("sp")!.f(12) !== 2) throw "calMap";
console.log("accept ok", V.cases.length, "cases");
