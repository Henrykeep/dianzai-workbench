import { Receipts, RECEIPT_LABEL, blockedCard, newBlockers, ACK_TIMEOUT_MS, newMsgId, noticeView, NoticeGate } from "../src/receipt.ts";
import { ACTIONS } from "../src/progress.ts";
// 假定时器：手动推进
let now = 0; const q: { at: number; f: () => void; dead?: boolean }[] = [];
const setT = (f: () => void, ms: number) => { const t = { at: now + ms, f }; q.push(t); return t as any; };
const clrT = (t: any) => { t.dead = true; };
const adv = (ms: number) => { now += ms; q.filter(t => !t.dead && t.at <= now).forEach(t => { t.dead = true; t.f(); }); };
const log: string[] = [];
const R = new Receipts((id, s) => log.push(`${id}:${RECEIPT_LABEL[s]}`), setT, clrT);
// 已发送 → queued 已送达 → running 处理中
R.sent("a"); if (log.pop() !== "a:已发送") throw "立即已发送";
R.ack({ msg_id: "a", state: "queued" }); if (log.pop() !== "a:已送达") throw "queued";
adv(ACK_TIMEOUT_MS + 1); if (R.state("a") !== "queued") throw "有 ack 不超时";
R.ack({ msg_id: "a", state: "running" }); if (log.pop() !== "a:处理中") throw "running";
// 3 s 无 ack → 未送达；迟到 ack 撤销
R.sent("b"); adv(2999); if (R.state("b") !== "sent") throw "3 s 内不判";
adv(2); if (log.pop() !== "b:未送达") throw "3 s 未送达";
R.ack({ msg_id: "b", state: "queued" }); if (R.state("b") !== "queued") throw "迟到 ack";
// 连发三条：每条各自回执（r6 第 2、3 条无回执的回归）
for (const id of ["c1", "c2", "c3"]) R.sent(id);
R.ack({ msg_id: "c2", state: "queued" }); R.ack({ msg_id: "c3", state: "queued" }); R.ack({ msg_id: "c1", state: "running" });
if (R.state("c1") !== "running" || R.state("c2") !== "queued" || R.state("c3") !== "queued") throw "并发回执";
// 有回答也算送达；未知 msg_id / 坏 state 忽略
R.sent("d"); R.replied("d"); adv(5000); if (R.state("d") !== "done") throw "回答算送达";
if (R.ack({ msg_id: "zz", state: "queued" }) || R.ack({ msg_id: "a", state: "bogus" as any })) throw "忽略未知";
if (newMsgId() === newMsgId()) throw "msg_id 唯一";
// blocked → 「已急停，请先解除」，正文 message，按钮走 resolveFix → 「解除急停」
R.sent("e"); R.ack({ msg_id: "e", state: "blocked", reason: "estop", message: "板子已急停（心跳丢失），这条消息暂停执行", fix_action: "estop_clear" });
if (R.state("e") !== "blocked") throw "blocked";
const k = blockedCard({ msg_id: "e", state: "blocked", reason: "estop", message: "板子已急停（心跳丢失），这条消息暂停执行", fix_action: "estop_clear" }, () => true);
if (k.title !== "已急停，请先解除" || k.why !== "板子已急停（心跳丢失），这条消息暂停执行") throw "blocked 卡";
if (k.other !== null || !k.fix.includes("红条或顶栏")) throw "r8pre：Agent 卡不给解除按钮，只写文字 " + JSON.stringify(k.other);
if (ACTIONS.estop_clear.ui !== "cmd-r") throw "解除走人点的 R 键入口";
// progress.changed：只对新 blocker 发消息（#28：急停打断自整定）
const seen = new Set<string>();
newBlockers(seen, [{ code: "params_not_saved" }]);
const nb = newBlockers(seen, [{ code: "params_not_saved" }, { code: "estop", fix_action: "estop_clear" } as any]);
if (nb.length !== 1 || nb[0].code !== "estop") throw "新 blocker";
if (newBlockers(seen, [{ code: "estop" }]).length) throw "旧 blocker 不重复";
// agent_notice：先结论，再发生了什么 / 原因来自 / 建议；human_only 标「需人工确认」；同 code 未清除前去重
const nv = noticeView({ blocker_code: "tune_interrupted", what: "自整定被急停打断", source: "heartbeat_lost", suggestion: "确认安全后解除急停", fix_action: "estop_clear", human_only: true });
if (!nv.head.startsWith("结论") || nv.lines[0] !== "发生了什么：自整定被急停打断" || !nv.lines[1].includes("heartbeat_lost") || !nv.lines[2].startsWith("建议") || nv.tag !== "需人工确认") throw "notice 视图";
if (noticeView({ blocker_code: "x", what: "y" }).tag) throw "非人工不标";
const G = new NoticeGate();
if (!G.offer("tune_interrupted") || G.offer("tune_interrupted")) throw "去重";
G.sync(["tune_interrupted"]); if (G.offer("tune_interrupted")) throw "未清除仍去重";
G.sync([]); if (!G.offer("tune_interrupted")) throw "清除后可再提示";
console.log("receipt ok");
