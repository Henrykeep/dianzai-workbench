import { readFileSync } from "node:fs";
import { SYMPTOMS, TAX, filterSym } from "../src/symptoms.ts";
const html = readFileSync("index.html", "utf8");   // 从 app/ui 跑
const steps = ["项目", "烧录", "模块", "联调", "标定", "调参", "评分", "封箱"];
for (const s of SYMPTOMS) {
  if (!TAX[s.tax]) throw "未知分类 " + s.tax;
  if (!s.acts.length) throw "症状没给去处 " + s.sym;
  for (const a of s.acts) {
    if (a.step && !steps.includes(a.step)) throw "未知步 " + a.step;
    for (const id of a.click ?? []) if (!html.includes(`id="${id}"`)) throw `index.html 没有 #${id}（${s.sym}）`;
  }
}
if (!filterSym("hardfault").length || !filterSym("断电").length || filterSym("").length !== SYMPTOMS.length) throw "filter";
console.log("symptoms ok");
