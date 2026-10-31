// 板上状态的显示（契约：status.run_mode / selftest / params_saved / params_hash / estop_cause）。
// 文案以侧车给的 message_zh / label_zh 为准，前端不拼原因；这里只决定显示什么、按钮能不能点。
export type RunMode = { mode: string; started?: boolean; label_zh: string };
export type Selftest = { pass: boolean; failed_items: { code: string; key: string; message_zh: string }[]; t?: number } | null;
export type EstopCause = { cause: string; cause_id?: number; message_zh: string; t?: number; run_mode?: string };
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

// run_selftest 出错：no_board → 「未连接板子」+「连接」（fix_action connect）；selftest_timeout → 「自检超时」+「重试」
export type SelftestErrView = { text: string; btn: { label: string; action: "connect" | "retry" } | null };
export function selftestErrView(e: { code?: string; message?: string; fix?: string; fix_action?: string } | null | undefined): SelftestErrView {
  if (e?.code === "no_board") return { text: "未连接板子", btn: { label: "连接", action: "connect" } };
  if (e?.code === "selftest_timeout") return { text: "自检超时", btn: { label: "重试", action: "retry" } };
  return { text: [e?.message, e?.fix].filter(Boolean).join(" · ") || "读取自检失败", btn: null };
}

// 封箱页只读：最近一次自检的结果与时间（封箱前检查项）。
// 是否「请重新自检」以本地服务给的 selftest.stale 为准，前端不推算；未通过也提示。字段未上线（stale 缺失）时只显示结果和时间。
export const RESELFTEST = "请重新自检";
export type SealSelftest = { text: string; when: string; need: boolean; why: string };
export function atMs(at: unknown): number | null {
  if (typeof at === "number" && isFinite(at)) return at < 1e11 ? at * 1000 : at;
  if (typeof at === "string" && at) { const t = Date.parse(at); return isNaN(t) ? null : t; }
  return null;
}
type SelftestSnap = NonNullable<Selftest> & { at?: string | number; params_hash_at?: string; stale?: boolean };
export function sealSelftestView(st: BoardStatus, seenAtMs: number | null, fmt = (t: number) => new Date(t).toLocaleTimeString("zh-CN", { hour12: false })): SealSelftest {
  const s = st.selftest as SelftestSnap | null | undefined;
  if (!s) return { text: "尚未自检", when: "", need: false, why: "" };
  const at = atMs(s.at) ?? seenAtMs;   // at：主机墙钟（带时区 ISO 8601；兼容秒 / 毫秒数字）；没有或解析不了时用界面收到的时刻
  const when = at ? fmt(at) : "";
  if (!s.pass) return { text: "自检未通过", when, need: true, why: `${s.failed_items.length} 项未通过` };
  if (s.stale === true) return { text: "自检通过", when, need: true, why: "自检之后参数已修改" };
  return { text: "自检通过", when, need: false, why: "" };
}
