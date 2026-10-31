// 例题 / 仿真板：界面不写死任何一道题、一块板（#80）。名字只来自后端声明：
// - 仿真板中文名：工程声明里的板名（declaredBoard），没有就用通用「仿真板」，原 id 只进悬停；
// - 「从示例开始」：候选例题取 list_ports 里的仿真板 id（后端从 examples/ 目录扫出），后端回 bad_example 就试下一个。
export type PortLike = { port: string; kind?: string };
export const SIM_RE = /^sim:([^+]+)$/;
export function exampleCandidates(ports: PortLike[] | undefined): string[] {
  const out: string[] = [];
  for (const p of ports ?? []) { const m = SIM_RE.exec(p.port); if (m && !out.includes(m[1])) out.push(m[1]); }
  return out;
}
export const simBoardZh = (declared?: string) => declared && declared.trim() ? declared.trim() : "仿真板";
// #104 下拉框仿真项：「仿真 · <应用名>」，应用名取 list_ports 声明（PORT_APP_F），没有就用目录名；+hw 标「当实板」
import { PORT_APP_F, PORT_DIR_F, pickStr } from "./fieldmap";
export function simPortLabel(p: PortLike & Record<string, unknown>): string {
  const m = /^sim:([^+]+)(\+hw)?$/.exec(p.port); if (!m) return "";
  return `仿真 · ${pickStr(p, PORT_APP_F) || pickStr(p, PORT_DIR_F) || m[1]}${m[2] ? "（当实板）" : ""}`;
}
