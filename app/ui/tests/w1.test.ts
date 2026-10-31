import { parseUsage, elapsedOf, fmtElapsed } from "../src/usage.ts";
import { infer, pageHead, PURPOSE, JOURNEY, viewStep, ACTIONS } from "../src/progress.ts";
const u = parseUsage({ text: "ok", usage: { tokens_in: 120, tokens_out: 30, elapsed_ms: 2400 } });
if (!u || u.tokens_in !== 120 || u.tokens_out !== 30 || u.elapsed_ms !== 2400) throw "usage 解析";
if (parseUsage("纯文本") !== null || parseUsage({ usage: {} }) !== null) throw "无 usage";
const ev = parseUsage({ type: "agent_usage", prompt: 10, completion: 5 });
if (!ev || ev.tokens_in !== 10 || ev.elapsed_ms !== undefined) throw "旧事件";
if (elapsedOf(u, 99) !== 2400 || elapsedOf(ev, 1234) !== 1234 || elapsedOf(null, 50) !== 50) throw "耗时来源";
if (fmtElapsed(1234) !== "本轮耗时 1.2 s" || fmtElapsed(80) !== "本轮耗时 80 ms" || fmtElapsed(5000).includes("token")) throw "耗时格式";
for (const j of JOURNEY) if (!PURPOSE[j.id]) throw "缺说明 " + j.id;
const base = { connected: true, estop: false, gainsZero: false, paramsDirty: false, selftestFail: false };
const p1 = infer({ ...base, current: "调参", visited: new Set(["调参"]) as any });
const h1 = pageHead(p1);
if (p1.next?.title !== "调参" || h1.action !== p1.next.action || h1.label !== "下发参数") throw "主按钮与 next 同源";
const p2 = infer({ ...base, current: "项目", visited: new Set(["项目", "调参"]) as any });
const h2 = pageHead(p2);
if (h2.goto !== "project" || !h2.label.startsWith("前往")) throw "已完成页指向 next";
if (pageHead(infer({ ...base, current: "项目", visited: new Set(["项目"]) as any })).label !== "新建工程") throw "读题页主按钮";
const e2 = parseUsage({ type: "agent_usage", usage: { elapsed_ms: 900 } });
if (!e2 || elapsedOf(e2, 5) !== 900 || e2.tokens_in !== undefined) throw "agent_usage 事件 usage";
console.log("w1 ok");
// 引导文案跟当前打开的页走（不跟进度 current）；每页主按钮不与页头常驻入口重复
{
  const p = infer({ ...base, current: "项目", visited: new Set(["项目"]) as any });
  for (const j of JOURNEY) for (const pg of j.pages) {
    if (viewStep(pg) !== j.id) throw `页 ${pg} → ${j.id}`;
    if (pageHead(p, j.id).text !== PURPOSE[j.id]) throw `${pg} 页引导文案串页`;
  }
  if (new Set(Object.values(PURPOSE)).size !== JOURNEY.length) throw "引导文案重复";
  if (!/自检/.test(PURPOSE.tune) || !/保存参数/.test(PURPOSE.tune) || !/自整定/.test(PURPOSE.tune)) throw "调参页文案";
  for (const [id, t] of Object.entries(PURPOSE)) for (const j of JOURNEY) if (j.id !== id && t.includes(`${j.title}页`)) throw `${id} 文案提到别页`;
  // 调参页 next=保存参数：页头已常驻 tb-save → 主按钮隐藏，只留入口表登记的 tb-save
  const pt = { ...p, current: "tune", next: { title: "调参", action: "params_flash", hint: "" } } as any;
  const resident = ["seal-selftest", "tb-save"];
  const h = pageHead(pt, "tune", resident);
  if (!h.hidden || h.action) throw "调参页主按钮与「保存参数」重复 " + JSON.stringify(h);
  if (ACTIONS.params_flash.ui !== "tb-save" || ACTIONS.run_selftest.ui !== "seal-selftest" || ACTIONS.run_selftest.step !== "调参") throw "入口 ui id";
  const h2 = pageHead({ ...pt, next: { title: "调参", action: "tune_relay", hint: "" } }, "tune", resident);
  if (h2.hidden || h2.label !== "自整定") throw "不重复的主按钮照常显示";
  // 每页可见主按钮的 ui 不与该页常驻按钮重复
  for (const a of Object.keys(ACTIONS)) { const r = pageHead({ ...pt, next: { title: "调参", action: a, hint: "" } }, "tune", resident); if (!r.hidden && r.action && resident.includes(ACTIONS[r.action]?.ui)) throw "重复主按钮 " + a; }
  console.log("page head ok");
}
