import { STEPS, LAYOUT, nextOf, hintText } from "../src/steps.ts";
if (STEPS.join() !== "项目,烧录,模块,联调,标定,调参,评分,封箱") throw "steps order";
if (nextOf("项目") !== "烧录" || nextOf("封箱") !== null) throw "nextOf";
for (const s of STEPS) if (!LAYOUT[s]) throw "layout " + s;
if (!LAYOUT["调参"].dock || LAYOUT["调参"].sideTab !== "agent") throw "调参 = 参数 + Agent 助手";
if (!hintText("调参", false).includes("先在左上角连接") || hintText("烧录", false).includes("先在左上角连接")) throw "connect hint";
if (!hintText("评分", true).includes("下一步：封箱") || !hintText("封箱", true).includes("最后一步")) throw "next hint";
console.log("steps ok");
