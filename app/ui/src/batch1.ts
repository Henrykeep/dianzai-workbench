// r9 batch-1 纯逻辑（无 DOM）：连接标签、仿真/实机标签、迭代锁、param_reject 文案、首页三步引导
export type LinkTag = { text: string; tone: "ok" | "off" | "busy" };
// 连接状态只看 link.state：已连接 / 断开+原因 / 重连中（已等 X s，Y s 后再试）
export function linkTag(m: { board?: string; reason?: string; cause_zh?: string; message_zh?: string } | null, since: number | null, now: number, nextS?: number | null): LinkTag {
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
