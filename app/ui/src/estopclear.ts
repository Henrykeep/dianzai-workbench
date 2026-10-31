// #41：急停解除（estop state:cleared / tx_locked true→false）后同一渲染节拍内清掉所有「请先解除急停」类提示：
// 告警条（#alerts）的急停/看门狗红条、Agent 面板的 blocked 卡与 estop blocker 消息、左侧导航与页头的 estop blocker。
// 只留一行中性历史（#alerts 里 .al-hist，不是红色、不带「解除急停」按钮）。
import { Alerts } from "./alerts";
export const ESTOP_KINDS = new Set(["estop", "watchdog"]);
// 所有急停阻塞提示都必须能被这个选择器选中（新加的提示请打 data-estop-blocker）
export const ESTOP_BLOCKER_SEL = ['[data-estop-blocker]', '.blk[data-code="estop"]', '.blk-note[data-code="estop"]', '.nav-blk [data-code="estop"]'];
type Rm = { remove(): void };
type Root = { querySelectorAll(sel: string): ArrayLike<Rm> | Iterable<Rm> };
export function purgeEstopBlockers(root: Root): number {
  let n = 0;
  for (const e of Array.from(root.querySelectorAll(ESTOP_BLOCKER_SEL.join(", ")) as ArrayLike<Rm>)) { e.remove(); n++; }
  // 导航下只剩空壳的 blocker 盒子一起去掉
  for (const b of Array.from(root.querySelectorAll(".nav-blk") as ArrayLike<Rm & { childElementCount?: number }>)) if (b.childElementCount === 0) b.remove();
  return n;
}
// 告警条里去掉急停 / 看门狗事件（时间线里仍有完整记录）
export function resolveEstopAlerts(al: Alerts) { al.list = al.list.filter(e => !ESTOP_KINDS.has(e.kind)); }
// 解除后急停 blocker 一律不算（本地服务 progress 可能晚一拍）
export const dropEstopBlockers = <T extends { code: string }>(bs: T[], latched: boolean) => latched ? bs : bs.filter(b => b.code !== "estop");
const hhmmss = (ms: number) => new Date(ms).toLocaleTimeString("zh-CN", { hour12: false });
export const historyLine = (prevHead: string, tMs: number) => `${hhmmss(tMs)} 急停已解除（之前：${prevHead}）`;
// 告警条该不该显示红条：只在锁存中或还有非急停的严重事件时
export const bannerRed = (al: Alerts, latched: boolean) => latched || al.list.some(e => !ESTOP_KINDS.has(e.kind));
