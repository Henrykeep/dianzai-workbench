import { readFileSync } from "node:fs";
import { editItems, codeFromName, STEPS_FLOW } from "../src/projflow.ts";
const html = readFileSync("index.html", "utf8");
for (const k of STEPS_FLOW) if (!html.includes(`data-f="${k}"`)) throw "项目页缺步骤卡 " + k;
for (const id of ["pf-code", "pf-dest", "pf-drop", "pf-file", "pf-proj", "pf-board", "pf-app", "pf-uv"]) if (!html.includes(`id="${id}"`)) throw "缺 #" + id;
const items = [{ id: "B1", part: "基本", score: 10, text: "a", metrics: [{ name: "t" }] }, { id: "B2", text: "b" }];
const out = editItems(items, [{ id: "B1 ", part: "基本", score: "12", text: "a2" }, { id: "B2", part: "", score: "", text: "b", del: true }]);
if (out.length !== 1 || out[0].score !== 12 || out[0].text !== "a2" || out[0].id !== "B1" || (out[0].metrics as any)[0].name !== "t") throw "editItems " + JSON.stringify(out);
const o2 = editItems([{ id: "B1", text: "a", score: 5 }], [{ id: "B1", part: "", score: "", text: "a" }]);
if ("score" in o2[0] || "part" in o2[0]) throw "空格子应删字段";
console.log("projflow ok");
for (const [fn, want] of [["H题_车载平衡滚球运动控制系统.pdf", "2026H"], ["2025E_xx.pdf", "2025E"], ["D 题 陆空.pdf", "2026D"], ["题目.pdf", ""]] as const)
  if (codeFromName(fn, 2026) !== want) throw `codeFromName ${fn} → ${codeFromName(fn, 2026)}`;
