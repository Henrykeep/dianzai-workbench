// 工具箱纯逻辑（无 DOM，可单测）：状态推导、分组、搜索、最近使用、修复动作。界面在 toolbox.ts。
import { toToolList, type ToolCard, type ToolList, type ToolStatus } from "./fieldmap";
import { TOOL_DECLS, type ToolDecl } from "./tooldecl";
import { STAGES } from "./stages";
import { REASONS_T, codeZh } from "./reasoncodes";

// 唯一阶段表：stages.ts（首页流程与工具箱分组共用）。后端 tool_list 给了 stages 就用后端的。
export const DEF_STAGES = STAGES.map(s => ({ id: s.id, title: s.title }));
export type Conn = { sidecar: boolean; board: boolean; sim?: boolean };
// 状态 → 原因码（中文一律 codeZh 查 reason_codes.json；表里还没有的码用这里的兜底中文，不露英文码）
export const STATUS_REASON: Record<Exclude<ToolStatus, "available">, string> = { no_sidecar: "sidecar_down", needs_board: "no_board", missing_dep: "missing_dep", not_integrated: "not_integrated" };
export const REASON_FALLBACK_ZH: Record<string, string> = {
  sidecar_down: "本地服务没有运行，工具连不上硬件", no_board: "还没有连接板子（或仿真板），也可能是 USB 线被拔掉了",
  missing_dep: "缺少这个工具需要的依赖", needs_real_serial: "现在连的是仿真板，这个工具要接真串口才能用", no_data: "没有收到数据", not_integrated: "这个工具还没接进工作台，先占一个位置", bad_arg: "参数不对",
  confirm_required: "这个操作会写文件或动板子，需要先确认", error: "工具运行出错",
};
// 修复动作默认值；reason_codes.json 条目里写了 fix_action 时以表为准
export const FIX_DEFAULT: Record<string, string> = { needs_real_serial: "connect_board", sidecar_down: "start_sidecar", no_board: "connect_board", missing_dep: "install_dep", bad_arg: "edit_params" };
export const FIX_LABEL: Record<string, string> = { start_sidecar: "启动本地服务", connect_board: "去连接板子", install_dep: "打开自检看缺什么", edit_params: "改参数", reconnect: "重新连接", confirm: "确认" };
export const STATUS_ZH: Record<ToolStatus, string> = { available: "可用", missing_dep: "缺依赖", needs_board: "需要连板", no_sidecar: "本地服务未运行", not_integrated: "尚未接入" };
export const STATUS_VARIANT: Record<ToolStatus, string> = { available: "success", missing_dep: "warning", needs_board: "warning", no_sidecar: "danger", not_integrated: "neutral" };
export const reasonZh = (code: string) => codeZh(code, REASON_FALLBACK_ZH);
export function fixFor(code: string | undefined): string | undefined {
  if (!code) return undefined;
  const e: any = REASONS_T.value()[code];
  return (typeof e?.fix_action === "string" && e.fix_action) || FIX_DEFAULT[code];
}
export function statusOf(d: Pick<ToolDecl, "built" | "needs"> & { real_port?: boolean }, c: Conn): ToolStatus {
  if (!d.built) return "not_integrated";
  if (d.needs !== "none" && !c.sidecar) return "no_sidecar";
  if (d.needs === "board" && !c.board) return "needs_board";
  if (d.real_port && c.sim) return "needs_board";
  return "available";
}
/** 本地声明 → 与接口 tool_list 同形的对象（再走 fieldmap.toToolList，接口上线后只换数据源） */
export function localToolList(decls: ToolDecl[], c: Conn, current: string, recent: string[]): any {
  return { stages: DEF_STAGES.map(s => s.id), current_stage: current, tools: decls.map(d => {
    const st = statusOf(d, c), rc = st === "available" ? undefined : st === "needs_board" && d.real_port && c.sim && c.board ? "needs_real_serial" : STATUS_REASON[st];
    return { id: d.id, stage: d.stage, icon: d.icon, name_zh: d.name_zh, summary_zh: d.summary_zh, status: st, reason_code: rc, fix_action: fixFor(rc),
      advanced: !!d.advanced, last_used: recent.includes(d.id) ? "local" : null, applies_to: d.applies_to, agent_callable: d.agent_callable, source: d.source, license: d.license };
  }) };
}
export function buildList(api: any | null, c: Conn, current: string, recent: string[]): ToolList {
  const l = toToolList(api ?? localToolList(TOOL_DECLS, c, current, recent), DEF_STAGES, current);
  // 接口给的状态是侧车视角；侧车本身断了时前端改成 no_sidecar（接口也到不了）
  if (!c.sidecar) l.tools = l.tools.map(t => t.status === "not_integrated" ? t : { ...t, status: "no_sidecar", reason: "sidecar_down", fix: fixFor("sidecar_down") });
  return l;
}
export type Group = { id: string; title: string; open: boolean; tools: ToolCard[] };
/** 当前阶段一组展开、排最前；其余按旅程顺序折叠；advanced 收进最后的「更多」；空组不出 */
export function groups(l: ToolList): Group[] {
  const g: Group[] = l.stages.map(s => ({ id: s.id, title: s.title, open: s.id === l.current, tools: l.tools.filter(t => t.stage === s.id && !t.advanced) }));
  const known = new Set(l.stages.map(s => s.id));
  const more = l.tools.filter(t => t.advanced || !known.has(t.stage));
  const out = [...g.filter(x => x.open), ...g.filter(x => !x.open)].filter(x => x.tools.length);
  if (more.length) out.push({ id: "__more", title: "更多", open: false, tools: more });
  return out;
}
export function search(l: ToolList, q: string): ToolCard[] {
  const k = q.trim().toLowerCase(); if (!k) return [];
  return l.tools.filter(t => [t.name, t.summary, t.id, t.source, ...t.appliesTo].some(s => s.toLowerCase().includes(k)));
}
export const RECENT_KEY = "dz.tb.recent";
export function loadRecent(st: Pick<Storage, "getItem"> | null): string[] {
  try { const v = JSON.parse(st?.getItem(RECENT_KEY) || "[]"); return Array.isArray(v) ? v.filter(x => typeof x === "string").slice(0, 6) : []; } catch { return []; }
}
export function pushRecent(st: Pick<Storage, "getItem" | "setItem"> | null, id: string): string[] {
  const r = [id, ...loadRecent(st).filter(x => x !== id)].slice(0, 6);
  try { st?.setItem(RECENT_KEY, JSON.stringify(r)); } catch { /* 隐私模式 */ }
  return r;
}
export const recentCards = (l: ToolList, recent: string[]) => recent.map(id => l.tools.find(t => t.id === id)).filter((t): t is ToolCard => !!t);
// 网页版侧车没开：xintai:// 由 exe 注册（tauri-plugin-deep-link，后端接）；拉不起来时给安装包下载
export const SIDECAR_START_URL = "xintai://start";
export const INSTALLER_URL = "https://github.com/Henrykeep/dianzai-workbench/releases";
