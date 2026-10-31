// #41：急停解除后同一渲染节拍内（同步、不等定时器）不留红条 / 「解除急停」卡；cause 为 null 时不显示 null
import { Alerts } from "../src/alerts.ts";
import { purgeEstopBlockers, resolveEstopAlerts, dropEstopBlockers, bannerRed, historyLine, ESTOP_BLOCKER_SEL } from "../src/estopclear.ts";
import { estopView, causeText, CAUSE_UNKNOWN, UNREPORTED } from "../src/estop.ts";
import { handleEstopMsg, onEstopEvent, markClearClick, markClearedShown, traces } from "../src/estopbtn.ts";
import { infer } from "../src/progress.ts";
// 极简假 DOM：元素带 class / data-code / data-estop-blocker / 文本
type El = { cls: string[]; code?: string; blk?: boolean; text: string; parent?: El; kids: El[]; remove(): void; childElementCount: number };
const mk = (cls: string, text = "", o: Partial<El> = {}, parent?: El): El => {
  const e: El = { cls: cls.split(" "), text, kids: [], parent, ...o, remove() { if (e.parent) e.parent.kids = e.parent.kids.filter(k => k !== e); }, get childElementCount() { return e.kids.length; } } as El;
  parent?.kids.push(e); return e;
};
const root = mk("root");
const all = (r: El): El[] => r.kids.flatMap(k => [k, ...all(k)]);
const match = (e: El, sel: string): boolean => {
  sel = sel.trim();
  if (sel === "[data-estop-blocker]") return !!e.blk;
  const m = /^\.([\w-]+)\[data-code="(\w+)"\]$/.exec(sel); if (m) return e.cls.includes(m[1]) && e.code === m[2];
  const d = /^\.([\w-]+) \[data-code="(\w+)"\]$/.exec(sel); if (d) return e.code === d[2] && !!e.parent?.cls.includes(d[1]);
  if (sel.startsWith(".")) return e.cls.includes(sel.slice(1));
  throw "未知选择器 " + sel;
};
(root as any).querySelectorAll = (sel: string) => all(root).filter(e => sel.split(",").some(s => match(e, s)));
// 锁存期间界面上的各种急停提示
const agentCard = mk("card down-card ag-err", "已急停，请先解除 · 解除急停", { blk: true }, root);
const agentNote = mk("msg bot blk-note", "已急停：急停已锁定 · 解除急停", { code: "estop" }, root);
const nav = mk("nav-blk", "", {}, root); mk("nb", "已急停 · 解除急停", { code: "estop" }, nav);
const hint = mk("blk", "已急停：急停已锁定 · 解除急停", { code: "estop" }, root);
const other = mk("blk", "参数未下发 · 下发", { code: "params_not_saved" }, root);
const AL = new Alerts();
AL.offer({ i: 1, kind: "estop", text: "急停", t: 0 } as any); AL.offer({ i: 2, kind: "watchdog", text: "心跳", t: 0 } as any);
if (!bannerRed(AL, true)) throw "锁存中应有红条";
// 收到 cleared：同步处理（一次渲染节拍内）
markClearClick();
let cleared = 0;
const t0 = performance.now();
handleEstopMsg({ type: "estop", state: "cleared" }, { setPhase() {}, showCleared() { cleared++; resolveEstopAlerts(AL); purgeEstopBlockers(root as any); markClearedShown(); }, toast() {} });
const dt = performance.now() - t0;
if (cleared !== 1) throw "cleared 未触发解除";
if (bannerRed(AL, false) || AL.list.length) throw "解除后还有急停红条";
const left = all(root).filter(e => /解除急停/.test(e.text));
if (left.length) throw "解除后还留着「解除急停」：" + left.map(e => e.text).join(" | ");
if (!all(root).includes(other)) throw "误删了非急停提示";
if (all(root).some(e => e.cls.includes("nav-blk"))) throw "空的导航 blocker 盒子没清";
if (dt > 16) throw `解除处理 ${dt.toFixed(1)} ms 超过一帧`;
// 打点字段仍在
const tr = traces.at(-1)! as any;
if (tr.clear_click == null || tr.cleared_shown == null || typeof tr.clear_to_cleared_ms !== "number") throw "__dzEstop 打点字段丢了";
// 非急停严重事件不受影响
const A2 = new Alerts(); A2.offer({ i: 3, kind: "crc", text: "CRC", t: 0 } as any); resolveEstopAlerts(A2);
if (!bannerRed(A2, false)) throw "CRC 告警不应被解除清掉";
// progress：解除后不再推断出 estop blocker；接口晚一拍给的 estop blocker 也丢掉
const ctx = { current: "调参", connected: true, estop: false, gainsZero: false, paramsDirty: false, selftestFail: false, visited: new Set() } as any;
if (infer(ctx).blockers.some((b: any) => b.code === "estop")) throw "推断仍有 estop blocker";
if (dropEstopBlockers([{ code: "estop" }, { code: "no_board" }], false).length !== 1) throw "未丢弃晚到的 estop blocker";
if (dropEstopBlockers([{ code: "estop" }], true).length !== 1) throw "锁存中不能丢";
// 历史只一行、中性
const h = historyLine("急停：在工作台上按了急停（按钮 / Esc / 空格）", Date.now());
if (h.includes("\n") || /请先解除|解除急停」/.test(h) || !h.includes("已解除")) throw "历史行 " + h;
// cause 为 null（重连后未上报）
for (const c of [null, undefined, "", "null", " NULL "]) if (causeText(c) !== CAUSE_UNKNOWN) throw "causeText " + c;
if (CAUSE_UNKNOWN !== "原因未知（重连后未上报）" || !UNREPORTED.includes(CAUSE_UNKNOWN)) throw "文案";
for (const v of [estopView({ source: "firmware:null" }, { cause: "null", message_zh: "null" }), estopView({ source: "" }, null), estopView(undefined, { message_zh: "" } as any)])
  if (/null|undefined/.test(v.head) || !v.head.includes(CAUSE_UNKNOWN)) throw "cause null 显示成 " + v.head;
void ESTOP_BLOCKER_SEL; void onEstopEvent;
console.log("✓ estopclear (#41)");
