import { simBoardZh } from "./examples";
// r9 batch-1 纯逻辑（无 DOM）：连接标签、仿真/实机标签、迭代锁、param_reject 文案、首页三步引导
export type LinkTag = { text: string; tone: "ok" | "off" | "busy" };
// 连接状态只看 link.state：已连接 / 断开+原因 / 重连中（已等 X s，Y s 后再试）
export function linkTag(m: { board?: string; reason?: string; cause_zh?: string; message_zh?: string } | null, since: number | null, now: number, nextS?: number | null, sidecarUp = true): LinkTag {
  if (!sidecarUp) return { text: "本地服务未连接", tone: "off" };   // #73 侧车不在时板子状态无从得知，绝不显示「已连接」
  const b = m?.board;
  if (b === "connected") return { text: "已连接", tone: "ok" };
  if (b === "lost" || m?.reason === "resuming") {
    const el = since != null ? Math.max(0, Math.round((now - since) / 1000)) : 0;
    return { text: `重连中 · 已 ${el} s${nextS != null ? ` · ${Math.max(0, Math.round(nextS))} s 后再试` : ""}`, tone: "busy" };
  }
  const why = m?.cause_zh || m?.message_zh || REASON_ZH[m?.reason ?? ""] || "";
  return { text: why ? `断开 · ${why}` : "断开", tone: "off" };
}
const REASON_ZH: Record<string, string> = { port_not_found: "找不到板子", port_ambiguous: "多块同型号板子", user: "已手动断开", unplugged: "USB 被拔出", timeout: "心跳超时" };
export const dataTag = (port: string | undefined | null): "仿真" | "实机" | "" => !port ? "" : /^sim:/.test(port) ? "仿真" : /^replay:/.test(port) ? "" : "实机";
// 心跳 bit17（hb_flags 里的「迭代中」）或本地迭代在跑：锁参数滑条与下发
export const ITER_FLAG = "迭代中";
export const iterLocked = (hbFlags: string[] | null | undefined, running: boolean) => running || (hbFlags ?? []).includes(ITER_FLAG);
export const ITER_LOCK_ZH = "迭代进行中";
// param_reject reason → 参数行下一句提示
export const REJECT_ZH: Record<string, string> = { range: "超出量程，板子没收", type: "类型不对（整型参数给了小数等），板子没收", state: "当前状态不允许改（如运行中 / 急停），板子没收", step: "单步改动过大，分几次小步改" };
export function rejectHint(r: { reason?: string | number; requested?: number; value?: number; current?: number }): string {
  const base = REJECT_ZH[String(r.reason)] ?? `板子拒绝（${r.reason}）`;
  const req = r.requested ?? r.value;
  return `${base}${req != null ? `：请求 ${+(+req).toPrecision(6)}` : ""}${r.current != null ? `，板上仍为 ${+(+r.current).toPrecision(6)}` : ""}`;
}
// 首页三步：选题目 → 接线 → 开始调参（卡片，不是全局步骤条）
export type Guide = { k: string; t: string; s: "done" | "cur" | "todo" }[];
export function guide(hasProject: boolean, connected: boolean, tuned: boolean): Guide {
  const done = [hasProject, hasProject && connected, hasProject && connected && tuned]; const cur = done.indexOf(false);
  return ["选题目", "接线", "开始调参"].map((t, i) => ({ k: ["req", "wire", "tune"][i], t, s: done[i] ? "done" : i === cur ? "cur" : "todo" }));
}
// 自动迭代进度：「第 2/8 轮，预算还剩 150 s」
export const iterProgress = (iter: number, rounds: number, leftS: number) => `第 ${Math.min(Math.max(iter, 1), rounds)}/${rounds} 轮，预算还剩 ${Math.max(0, Math.ceil(leftS))} s`;
// r9p3 去掉界面上的英文状态码：固件枚举名 → 中文（原文进悬停）
export const ENUM_ZH: Record<string, string> = { idle: "空闲", running: "运行中", run: "运行中", estop: "急停", fault: "故障", error: "故障", ready: "就绪", stopped: "已停止", stop: "已停止", calib: "标定中", init: "初始化", boot: "启动中", hold: "保持", step: "阶跃中", safe: "安全态", stall: "堵转" };
export const enumZh = (s: string) => ENUM_ZH[s.toLowerCase()] ?? s;
// 原因来源 → 中文
export const SOURCE_ZH: Record<string, string> = { ui: "在工作台上按了急停", button: "在工作台上按了急停", key: "在工作台上按了急停", board: "板子上报", firmware: "板子上报", hb_timeout: "心跳超时", watchdog: "心跳超时", host: "上位机停止", agent: "Agent 发起", sidecar: "本地服务", link: "连接中断", stall: "堵转保护", heartbeat_lost: "心跳丢失", hb_lost: "心跳丢失", limit: "限位触发" };
export const sourceZh = (s?: string | null) => !s ? "本地服务未上报" : SOURCE_ZH[s] ?? (/^[\x00-\x7f]+$/.test(s) ? "其他来源" : s);
// 仿真启动中：sim_starting {state:start|ready, elapsed_s?}
export const simStartText = (elapsedS: number) => `仿真启动中 · 已 ${Math.max(0, Math.round(elapsedS))} s`;
// 锁存期间要真禁用的写入按钮（会改板子 / 发运动 / 写参数）
export const WRITE_IDS = ["p-send", "p-def", "it-go", "it-write", "tb-save", "seal-mode", "fw-flash", "ag-step", "ag-relay", "ag-search", "ag-guard", "lines-btn", "pre-bbtn"];
export const WRITE_SEL = WRITE_IDS.map(i => "#" + i).join(",") + ",[data-write],.act-ok,.ag-accept,.snap-apply,.psl,input[id^=pi-],input[id^=pt-]";
export const ESTOP_WHY = "急停已锁存：先在红条上点「解除」";
// 纯 DOM 操作也放这里，便于测试（传入 root）
export function lockWritesIn(root: ParentNode, on: boolean) {
  if (on) root.querySelectorAll<any>(WRITE_SEL).forEach(e => { if (!e.dataset.estop) { e.dataset.estopTitle = e.title || ""; e.dataset.estop = e.disabled ? "was" : "1"; } e.disabled = true; e.title = ESTOP_WHY; });
  else root.querySelectorAll<any>("[data-estop]").forEach(e => { e.disabled = e.dataset.estop === "was"; e.title = e.dataset.estopTitle ?? ""; delete e.dataset.estop; delete e.dataset.estopTitle; });
}
// #71 写参数回执：只要带 reason（如 state），即便 ok:true 也算被拒，参数不算生效
export const paramRejected = (r: any) => !!r && (r.ok === false || r.status === "rejected" || (r.reason != null && r.reason !== "" && r.status !== "clamped"));
// 板子名：sim:<id> → 「仿真 · 工程声明的板名」（没声明 → 仿真板），原 id 只进悬停
export function boardName(port: string, declared?: string): string {
  if (!port) return "";
  const m = /^sim:(.+)$/.exec(port); if (m) return `仿真 · ${simBoardZh(declared)}`;
  if (/^replay:/.test(port)) return "回放";
  return /^(COM\d+|\/dev\/)/i.test(port) ? `串口 ${port.replace(/^\/dev\//, "")}` : "实物板";
}
// 参数生命周期标签（原 RAM / flash / yaml）
export const LIFE_ZH = { ram: "内存（未保存）", flash: "已存入 Flash", yaml: "已写入工程" } as const;
// 本地服务掉线横幅：三段 + 按钮，命令只在详情
export const SIDECAR_DOWN = { what: "本地服务没有响应", why: "本地服务进程未运行或已退出（桌面版会自动重启它）", fix: "等几秒自动恢复；仍不行就点「重新连接」", raw: "开发模式手动启动：python -m dzbench" };
