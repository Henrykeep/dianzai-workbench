// 板上状态的显示（契约：status.run_mode / selftest / params_saved / params_hash / estop_cause）。
// 文案以侧车给的 message_zh / label_zh 为准，前端不拼原因；这里只决定显示什么、按钮能不能点。
export type RunMode = { mode: string; started?: boolean; label_zh: string };
export type Selftest = { pass: boolean; failed_items: { code: string; key: string; message_zh: string }[]; t?: number } | null;
export type EstopCause = { cause: string; cause_id?: number; message_zh: string; value?: unknown; t?: number; run_mode?: string };
export type BoardStatus = { run_mode?: RunMode; selftest?: Selftest; params_saved?: boolean | null; params_hash?: string; estop_cause?: EstopCause | null };
type Rpc = (op: string, a?: any) => Promise<any>;
const missing = (e: any) => /bad_op|未知操作|unknown op/i.test(`${e?.code ?? ""} ${e?.message ?? ""}`);

// 调参页「保存参数」旁的状态
export function savedView(st: BoardStatus, savedAt: string | null): string {
  if (st.params_saved === false) return `参数未保存${st.params_hash ? ` · ${st.params_hash}` : ""}`;
  if (st.params_saved === true && savedAt) return `已保存 ${savedAt}`;
  return "";
}
export async function saveParams(rpc: Rpc): Promise<{ ok: boolean; note?: string; disable?: boolean }> {
  try { await rpc("save_params"); return { ok: true }; }
  catch (e: any) { return missing(e) ? { ok: false, disable: true, note: "本地服务暂不支持保存参数（save_params 接口未就绪）" } : { ok: false, note: e?.message ?? String(e) }; }
}
// 封箱页「切换模式」：参数未保存不让切
export function modeGate(st: BoardStatus): { enabled: boolean; reason: string } {
  if (st.params_saved === true) return { enabled: true, reason: "" };
  if (st.params_saved === false) return { enabled: false, reason: "参数未保存：先在调参页点「保存参数」，保存后才能切换运行模式" };
  return { enabled: false, reason: "板子未上报参数保存状态，暂不能切换运行模式" };
}
export const otherMode = (m?: RunMode) => (m?.mode === "standalone" ? "tethered" : "standalone");
export const CONFIRM_TEXT = "脱机后断开主机即可上电运行，心跳丢失不再停车";
// 两段式：先 confirmed=false；侧车回 needs_confirm 才弹确认卡，用户确认后带 confirmed=true 再调
export async function switchMode(rpc: Rpc, mode: string, confirm: (text: string) => Promise<boolean>): Promise<{ ok: boolean; note?: string; disable?: boolean; cancelled?: boolean }> {
  try {
    const r = await rpc("set_run_mode", { mode, confirmed: false });
    if (r?.needs_confirm) {
      if (!(await confirm(CONFIRM_TEXT))) return { ok: false, cancelled: true };
      await rpc("set_run_mode", { mode, confirmed: true });
    }
    return { ok: true };
  } catch (e: any) {
    return missing(e) ? { ok: false, disable: true, note: "本地服务暂不支持切换运行模式（set_run_mode 接口未就绪）" } : { ok: false, note: e?.message ?? String(e) };
  }
}
export const estopMessage = (st: BoardStatus) => st.estop_cause?.message_zh || null;
export const selftestFailures = (st: BoardStatus) => (st.selftest && !st.selftest.pass ? st.selftest.failed_items.map(i => i.message_zh) : []);
