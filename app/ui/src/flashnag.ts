// #63「未写入 Flash」只在「保存参数」旁边出现一次；进度/Agent/导航里一律不提。
// 刚连上（读回等于 Flash）或用户没改过参数：不提示。用户改过参数（下发/恢复/迭代写入）且板上报 params_saved=false：提示。
export const FLASH_CODE = "params_not_saved";
export const FLASH_NOTE = "未写入 Flash";
export class FlashNag {
  changed = false;
  onConnect() { this.changed = false; }
  onUserChange() { this.changed = true; }
  onSaved() { this.changed = false; }
  label(st: { params_saved?: boolean | null } | null | undefined, savedAt: string | null): string {
    if (st?.params_saved === false) return this.changed ? FLASH_NOTE : "";
    return st?.params_saved === true && savedAt ? `已保存 ${savedAt}` : "";
  }
}
const isFlash = (x: any) => x?.code === FLASH_CODE || x?.blocker_code === FLASH_CODE || x?.action === "params_flash" || x?.fix_action === "params_flash" || /flash/i.test(String(x?.message ?? x?.message_zh ?? x?.text ?? ""));
export const dropFlashBlockers = <T>(bs: T[] = []): T[] => bs.filter(b => !isFlash(b));
export function stripFlash<P extends { blockers?: any[]; next?: any; steps?: any[] }>(p: P | null | undefined): P | null | undefined {
  if (!p) return p;
  p.blockers = dropFlashBlockers(p.blockers ?? []);
  if (p.next && isFlash(p.next)) p.next = null;
  if (Array.isArray(p.steps)) for (const s of p.steps) if (Array.isArray(s?.blockers)) s.blockers = dropFlashBlockers(s.blockers);
  return p;
}
export const isFlashNotice = (n: any) => isFlash(n);
