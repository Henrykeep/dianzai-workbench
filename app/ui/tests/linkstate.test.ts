import { linkView, runState } from "../src/linkmsg.ts";
import { conn, onLinkState } from "../src/conn.ts";
const eq = (a: any, b: any, m: string) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw m + " " + JSON.stringify(a); };
eq(linkView({ board: "lost", reason: "resuming" }), { text: "连接中断，正在重连…", tone: "neutral", portAttn: false }, "resuming 中性");
eq(linkView({ board: "disconnected", reason: "port_not_found" }).text, "未找到上次使用的板子。请检查 USB 连接后点「连接」。", "not_found");
const am = linkView({ board: "disconnected", reason: "port_ambiguous" });
if (am.text !== "检测到多块同型号的板子，请选择要连接的端口。" || !am.portAttn) throw "ambiguous 高亮端口";
if (linkView({ board: "connected" }).text) throw "已连接无横幅";
// 断线前运行中 → 断线 → 重连：显示待机，且没有任何自动发出的指令（mock 事件 + 记录 rpc）
const sent: string[] = [];
const rpc = (op: string) => { sent.push(op); };
runState.fromBoard({ run: "running" }); if (runState.get() !== "running") throw "上报运行中";
for (const m of [{ board: "lost", reason: "resuming" }, { board: "connected" }]) { onLinkState(m); runState.onLink(m.board); }
if (runState.get() !== "standby") throw "重连后应待机";
if (!conn.get().board) throw "已连接";
if (sent.length) throw "重连后不应自动发指令：" + sent; void rpc;
runState.fromBoard({ run: "standby" }); if (runState.get() !== "standby") throw "板子上报待机";
console.log("linkstate ok"); process.exit(0);
