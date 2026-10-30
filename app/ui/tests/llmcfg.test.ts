import { readFileSync } from "node:fs";
import { modelLister, modelView, redactKey, type El, type ModelList } from "../src/llmcfg.ts";
// 假 Key：只在测试里出现，断言任何渲染输出都不含它
const KEY = "sk-test-0000FAKEKEY1111";
const html = readFileSync("index.html", "utf8");
for (const id of ["cfg-st", "cfg-models", "cfg-model", "cfg-key", "cfg-list", "cfg-retry"]) if (!html.includes(`id="${id}"`)) throw "缺 #" + id;

function rig(resp: ModelList | Error, model = "") {
  const focused: string[] = [], calls: unknown[] = [];
  const mk = (id: string): El => ({ value: "", placeholder: "", innerHTML: "", className: "", hidden: id === "cfg-retry", disabled: false, focus: () => focused.push(id) });
  const els: Record<string, El> = Object.fromEntries(["cfg-st", "cfg-models", "cfg-model", "cfg-key", "cfg-list", "cfg-retry"].map(i => [i, mk(i)]));
  els["cfg-model"].value = model; els["cfg-key"].value = KEY;
  const l = modelLister({
    call: async (op, a) => { calls.push([op, a]); if (resp instanceof Error) throw resp; return resp; },
    el: id => els[id], form: () => ({ provider: "x", base_url: "https://api.example/v1", model: els["cfg-model"].value, api_key: KEY }), preset: () => "preset-model",
  });
  const rendered = () => Object.entries(els).filter(([k]) => k !== "cfg-key").map(([, e]) => e.innerHTML + e.value + e.placeholder).join("|");
  return { l, els, focused, calls, rendered };
}
const noKey = (s: string, w: string) => { if (s.includes(KEY) || s.includes("0000FAKEKEY1111")) throw w + "：渲染出了 Key"; };

(async () => {
// 1 成功：列表填入 datalist，可选中；加载中有状态、按钮禁用
{
  const t = rig({ ok: true, models: ["deepseek-v4.1-flash", "deepseek-v4.1-pro"] }, "old-model");
  const p = t.l.load();
  if (!t.els["cfg-st"].className.includes("busy") || !t.els["cfg-list"].disabled) throw "加载状态";
  await p;
  if (t.calls.length !== 1 || (t.calls[0] as any)[0] !== "agent_models") throw "未调 agent_models";
  if (!t.els["cfg-models"].innerHTML.includes('value="deepseek-v4.1-pro"')) throw "列表未渲染";
  if (t.els["cfg-model"].value !== "" || !t.els["cfg-st"].innerHTML.includes("已获取 2 个")) throw "成功态";
  if (t.els["cfg-list"].disabled || !t.els["cfg-retry"].hidden || t.focused.at(-1) !== "cfg-model") throw "成功后焦点 / 按钮";
  t.els["cfg-model"].value = "deepseek-v4.1-pro";   // 用户选中
  await t.l.load();
  if (t.els["cfg-model"].value !== "deepseek-v4.1-pro" || !t.els["cfg-st"].innerHTML.includes("当前为 deepseek-v4.1-pro")) throw "选中保留";
  noKey(t.rendered(), "成功");
}
// 2 unsupported / manual_model → 手动填写，预设兜底；旧返回无 reason 同样处理
for (const r of [{ ok: false, models: [], reason: "unsupported", fix_action: "manual_model", message: "该服务未提供模型列表接口（HTTP 404）" }, { ok: false, models: [], message: "旧返回" }] as ModelList[]) {
  const t = rig(r); await t.l.load();
  if (t.els["cfg-model"].value !== "preset-model" || t.els["cfg-models"].innerHTML !== "" || t.focused.at(-1) !== "cfg-model") throw "unsupported 回退 " + r.message;
  if (!t.els["cfg-st"].className.includes("warn") || !t.els["cfg-retry"].hidden || !t.els["cfg-st"].innerHTML.includes("预设模型")) throw "unsupported 文案";
}
// 3 auth / check_key → 鉴权失败，焦点到 Key；报错原文里回显的 Key 被打码
{
  const t = rig({ ok: false, models: [], reason: "auth", fix_action: "check_key", message: `HTTP 401 Authorization: Bearer ${KEY}` }, "m1"); await t.l.load();
  if (!t.els["cfg-st"].innerHTML.includes("鉴权失败") || t.focused.at(-1) !== "cfg-key" || t.els["cfg-model"].value !== "m1") throw "auth";
  noKey(t.rendered(), "auth");
}
// 4 error / retry 与调用异常 → 显示「重试」，点重试再请求一次
for (const r of [{ ok: false, models: [], reason: "error", fix_action: "retry", message: "无法连接服务：timed out" } as ModelList, new Error("ws closed " + KEY)]) {
  const t = rig(r); await t.l.load();
  if (t.els["cfg-retry"].hidden || !t.els["cfg-st"].innerHTML.includes("重试") || !t.els["cfg-st"].className.includes("bad")) throw "error 重试";
  await t.l.load(); if (t.calls.length !== 2) throw "重试未再请求";
  noKey(t.rendered(), "error");
}
// 5 contest_mode → 固定提示，不自动重试
{
  const t = rig({ ok: false, models: [], reason: "contest_mode" }); await t.l.load();
  if (!t.els["cfg-st"].innerHTML.includes("比赛模式下未启用云端，不请求外部服务") || !t.els["cfg-retry"].hidden) throw "contest_mode";
  await t.l.auto(); await t.l.auto();
  if (t.calls.length !== 1) throw "contest_mode 不应自动重试";
}
// 6 空列表单独提示
if (!modelView({ ok: true, models: [] }, "", "p", KEY).html.includes("为空")) throw "空列表";
// 7 Key 不渲染：打码函数 + 消息里各种形式
if (redactKey(`key=${KEY} x`, KEY).includes(KEY) || redactKey("Bearer abc.def", "").includes("abc")) throw "redact";
// 8 界面禁用紫色：配置弹窗相关样式不得出现紫色色相
const css = readFileSync("src/style.css", "utf8").split("\n").filter(l => l.includes(".dlg.llm")).join("\n");
for (const m of css.matchAll(/oklch\([^)]*?\s([\d.]+)\s*(?:\/|\))/g)) if (+m[1] >= 270 && +m[1] <= 330) throw "紫色 " + m[0];
if (/purple|violet|#(8b5cf6|a855f7|7c3aed|9333ea)/i.test(css)) throw "紫色";
console.log("llmcfg ok");
})().catch(e => { console.error(e); process.exit(1); });
