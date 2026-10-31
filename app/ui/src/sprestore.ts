// 「恢复急停前目标」：只在设定值通道 hold === "latched"（板子会一直保持下发的目标）时出现；
// hold 缺省 / "timeout"（超时归零）→ 不给按钮，只留灰条「重新开始实验」。不看 cmd_timeout_ms，不连发。
// 点击 = 调一次 setpoint_set {name, value}；值来自 sp_before_latch，没有则用界面兜底值（RestoreTarget）。
export type Hold = "latched" | "timeout" | string | null | undefined;
type HoldSrc = { status?: any; fields?: { name: string; hold?: Hold }[]; params?: { name: string; hold?: Hold }[] };
// hold 由侧车透传：status.hold[name] / status.sp_hold、link_schema 通道字段、参数表，任一处给出即可
export function holdOf(name: string | null | undefined, src: HoldSrc): Hold {
  if (!name) return undefined;
  const st = src.status ?? {};
  return st.hold?.[name] ?? st.sp_hold ?? src.fields?.find(f => f.name === name)?.hold ?? src.params?.find(p => p.name === name)?.hold;
}
export const restoreAllowed = (h: Hold) => h === "latched";
export type RestoreErr = { code?: string; message?: string; message_zh?: string } | null;
export const KEEP_ON = new Set(["estop_locked", "iter_busy", "invalid_param"]);
// 结果 → 按钮是否留着 + 旁边的说明。成功：收起；hold_timeout：收起并写原因；其余已知错误：留按钮写 message_zh
export function restoreOutcome(err: RestoreErr): { keep: boolean; note: string } {
  if (!err) return { keep: false, note: "" };
  const msg = err.message_zh || err.message || "下发失败";
  if (err.code === "hold_timeout") return { keep: false, note: msg };
  return { keep: true, note: msg };   // KEEP_ON 与未知错误：按钮留着，可再点
}
// 点击：只发一次；in-flight 时重复点击忽略
export async function restoreClick(rpc: (op: string, a: Record<string, unknown>) => Promise<unknown>, name: string, value: number, busy: { on: boolean }): Promise<{ keep: boolean; note: string } | null> {
  if (busy.on) return null;
  busy.on = true;
  try { await rpc("setpoint_set", { name, value }); return restoreOutcome(null); }
  catch (e) { return restoreOutcome(e as RestoreErr); }
  finally { busy.on = false; }
}
