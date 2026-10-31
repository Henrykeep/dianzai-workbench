// r9p6 批次 2：状态位白话、链路质量、重连倒计时、命令面板、环层级 —— 纯函数，界面只调用这里
import { HB_F, SENSOR_SAT_ZH, toLoops, type Loop } from "./fieldmap";
import type { Cell } from "./hbstrip";
const DASH = "—";
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

// 1) 状态位 → 白话。已知标志给一句人话；未知码写「未知（代码 n）」，绝不只甩一个码
const FLAG_PLAIN: Record<string, string> = { 安全态: "已进入安全态（输出关闭）", 堵转: "检测到电机堵转", 急停: "板子处于急停", 自检失败: "上电自检没通过", 脱机模式: "脱机模式", 脱机运行中: "脱机运行中", 参数未保存: "参数改了还没存 Flash", 迭代中: "自动迭代进行中" };
const RESET_PLAIN: Record<string, string> = { 上电: "正常上电", 看门狗: "看门狗复位（程序卡死过）", 内核锁死: "内核锁死后复位", 软件: "软件复位", 按键: "按了复位键", 低电压: "电压过低复位" };
export function statusWords(st: any): { reset: string; flags: string[] } {
  const r = st?.[HB_F.reset];
  const code = typeof r === "string" ? /^#(\d+)$/.exec(r) : null;
  const reset = r == null || r === "" ? "" : code ? `未知复位原因（代码 ${code[1]}）` : RESET_PLAIN[r] ?? String(r);
  const flags = (Array.isArray(st?.[HB_F.flags]) ? st[HB_F.flags] : []).map((f: unknown) => FLAG_PLAIN[String(f)] ?? (/^(bit|0x|#)?\d+$/i.test(String(f)) ? `未知状态位 ${f}` : String(f)));
  if (st?.[HB_F.sat] === true && !flags.includes(SENSOR_SAT_ZH)) flags.push(SENSOR_SAT_ZH);   // 实时：每次 status 重算，false 即消失
  return { reset, flags };
}

// 2) 链路质量：只用心跳格已有的 fps / crc / drops；没有数据一律「—」
export type Quality = { text: string; tone: "ok" | "warn" | "bad" | "off"; tip: string };
export function linkQuality(cells: Cell[] | null | undefined, n = 10): Quality {
  const c = (cells ?? []).slice(-n).filter(x => fin(x?.fps));
  if (!c.length) return { text: `链路 ${DASH}`, tone: "off", tip: "还没收到链路统计" };
  const fps = c.reduce((s, x) => s + x.fps, 0) / c.length;
  const bad = c.every(x => fin(x.crc) && fin(x.drops)) ? c.reduce((s, x) => s + x.crc + x.drops, 0) : null;
  const tot = c.reduce((s, x) => s + x.fps, 0);
  const loss = bad == null ? null : tot + bad > 0 ? bad / (tot + bad) * 100 : 0;
  const tone = fps <= 0 ? "off" : loss == null ? "ok" : loss >= 5 ? "bad" : loss > 0.5 ? "warn" : "ok";
  const word = tone === "off" ? "无数据帧" : tone === "bad" ? "差" : tone === "warn" ? "一般" : "良好";
  const lossT = loss == null ? DASH : `${loss.toFixed(1)}%`;
  return { text: `链路 ${word} · ${Math.round(fps)} 帧/s · 丢包 ${lossT}`, tone, tip: `最近 ${c.length} s 平均：${fps.toFixed(1)} 帧/s；坏帧 + 丢帧 ${bad ?? DASH}；丢包率 ${lossT}` };
}

// 3) 本地服务断开横幅的重连细节
export function reconnectText(downSince: number | null, attempt: number, nextAt: number | null, now: number): string {
  if (downSince == null) return "";
  const el = Math.max(0, Math.round((now - downSince) / 1000));
  const nx = nextAt == null ? DASH : `${Math.max(0, (nextAt - now) / 1000).toFixed(1)} s 后`;
  return `已断开 ${el} s · 已自动重连 ${attempt} 次 · 下一次 ${nx}`;
}

// 4) 命令面板：只放主要动作和页面，模糊匹配（子串 / 拼音首字母不做，避免误命中）
export type Cmd = { id: string; title: string; hint?: string; keys?: string };
export function filterCmds(cmds: Cmd[], q: string): Cmd[] {
  const t = q.trim().toLowerCase(); if (!t) return cmds;
  const words = t.split(/\s+/);
  return cmds.filter(c => { const s = `${c.title} ${c.hint ?? ""}`.toLowerCase(); return words.every(w => s.includes(w)); });
}

// 5) 环层级说明：任意层数；缺字段显示「—」
export function loopLine(schema: any, active?: string): string {
  const ls: Loop[] = toLoops(schema); if (!ls.length) return "";
  const N = Math.max(ls.length, ...ls.map(l => l.level ?? 0));
  const cur = ls.find(l => l.name === active) ?? null;
  const lv = cur ? (cur.level != null ? `第 ${cur.level}/${N} 层` : `第 ${DASH} 层`) : `共 ${N} 层`;
  const lock = cur?.locked.length ? ` · 已锁定：${cur.locked.join("、")}` : "";
  return `${lv}${cur ? ` · ${cur.name}` : ""}${lock}`;
}

// 6) 图表缩放：拖选区间（太窄忽略），返回 [min,max] 或 null
export function zoomSel(a: number, b: number, minSpan = 1e-3): [number, number] | null {
  if (!fin(a) || !fin(b)) return null;
  const lo = Math.min(a, b), hi = Math.max(a, b);
  return hi - lo < minSpan ? null : [lo, hi];
}
// 7) 快照模式标签：未知模式原样显示，不再默认成「位置环」
const MODE_ZH: Record<string, string> = { speed: "速度环", position: "位置环", pos: "位置环", current: "电流环", angle: "角度环", temp: "温度环" };
export const modeZh = (m: string) => MODE_ZH[m] ?? m;
