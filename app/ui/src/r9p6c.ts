// r9p6c 复审修正（纯逻辑，无 DOM）
import { BOARD_F } from "./fieldmap";
import type { LinkTag } from "./batch1";
// 1) 连接状态唯一来源：顶栏按钮和底栏标签都由同一个 linkTag 结果推出，不再各看各的
export function connButton(t: LinkTag): { text: string; pri: boolean; title: string } {
  if (t.tone === "ok") return { text: "断开连接", pri: false, title: `当前：${t.text}；点击断开（Ctrl+O）` };
  if (t.tone === "busy") return { text: "停止重连", pri: false, title: `当前：${t.text}；点击放弃重连（Ctrl+O）` };
  return { text: "连接", pri: true, title: `当前：${t.text}；点击连接（Ctrl+O）` };
}
// 2) 板子名：只用工程声明的名字（schema title/name → 当前项目名），「仿真」标签只出现一次（由 dtag 负责）
export function declaredBoard(schema: any, project: any): string {
  for (const k of BOARD_F.schema) { const v = schema?.[k]; if (typeof v === "string" && v.trim()) return v.trim(); }
  const p = project?.[BOARD_F.project]; if (typeof p === "string" && p.trim()) return p.trim();
  const m = /([^/\\]+)[/\\]app\.ya?ml$/.exec(String(schema?.[BOARD_F.path] ?? ""));   // 声明文件所在目录名 = 工程名
  return m ? m[1] : "";
}
export function boardLabel(port: string, declared: string): string {
  if (!port) return "";
  const sim = /^sim:/.test(port);
  if (declared) return declared;
  if (sim) return "";   // 「仿真」已由数据来源标签显示一次
  if (/^replay:/.test(port)) return "回放";
  return /^(COM\d+|\/dev\/)/i.test(port) ? `串口 ${port.replace(/^\/dev\//, "")}` : "实物板";
}
// 顶栏下拉：连着的那一项写声明名，前缀「仿真 · 」只加一次
export const portOption = (port: string, declared: string) => /^sim:/.test(port) ? (declared ? `仿真 · ${declared}` : "仿真") : boardLabel(port, declared) || port;
// 3) 通道单位唯一来源：标定后的单位优先，否则声明单位；读数、轴、每格、悬停都用它
export const chUnit = (f: { name: string; unit?: string }, cal: Map<string, { unit: string }>) => cal.get(f.name)?.unit ?? f.unit ?? "";
// 4) 底栏右侧一句话：短句上屏，全文进悬停
export function shortHint(parts: string[], max = 18): { text: string; title: string } {
  const full = parts.filter(Boolean).join("  ·  ");
  if (!full) return { text: "", title: "" };
  const first = parts.filter(Boolean)[0];
  const text = first.length > max ? first.slice(0, max - 1) + "…" : first;
  return { text: parts.filter(Boolean).length > 1 ? `${text}（+${parts.filter(Boolean).length - 1}）` : text, title: full };
}
// 4) 参数第二行中文说明：只来自声明的 desc；没有就不显示
export const paramDesc = (p: { desc?: string }) => typeof p.desc === "string" ? p.desc.trim() : "";
// 5) 参数区头部：一个状态标签，点开看五站明细
export type LifeSum = { text: string; tone: "warn" | "info" | "ok"; rows: [string, string][] };
export function lifeSummary(pending: number, offDefault: number, nsnap: number): LifeSum {
  const rows: [string, string][] = [["草稿", pending ? `${pending} 待下发` : "无草稿"], ["内存（未保存）", offDefault ? `${offDefault} 个≠默认` : "=默认"], ["快照", `${nsnap} 个`], ["已存入 Flash", "去封箱"], ["已写入工程", "去封箱"]];
  if (pending) return { text: `${pending} 项待下发`, tone: "warn", rows };
  if (offDefault) return { text: "已下发 · 未保存", tone: "info", rows };
  return { text: "与默认一致", tone: "ok", rows };
}
