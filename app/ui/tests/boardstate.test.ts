import { savedView, saveParams, modeGate, otherMode, switchMode, estopMessage, selftestFailures, CONFIRM_TEXT, selftestErrView, sealSelftestView, RESELFTEST } from "../src/boardstate.ts";
import { ACTIONS, resolveFix } from "../src/progress.ts";
const bad = async () => { throw { code: "bad_op", message: "未知操作" }; };
(async () => {
  if (savedView({ params_saved: false, params_hash: "a1b2c3" }, null) !== "参数未保存 · a1b2c3") throw "未保存+hash";
  if (savedView({ params_saved: true }, "02:40:11") !== "已保存 02:40:11" || savedView({ params_saved: null }, null) !== "") throw "已保存时间 / null";
  const calls: any[] = []; const rpc = async (op: string, a?: any) => { calls.push([op, a]); return op === "set_run_mode" && !a.confirmed ? { needs_confirm: true } : { ok: true }; };
  if (!(await saveParams(rpc)).ok || calls[0][0] !== "save_params") throw "save_params";
  const s0 = await saveParams(bad); if (s0.ok || !s0.disable || !s0.note!.includes("未就绪")) throw "save 接口不可用";
  // 切换模式门槛
  if (modeGate({ params_saved: false }).enabled || !modeGate({ params_saved: false }).reason.includes("保存参数")) throw "未保存不让切";
  if (modeGate({ params_saved: null }).enabled || !modeGate({ params_saved: true }).enabled) throw "null / true";
  if (otherMode({ mode: "tethered", label_zh: "联机" }) !== "standalone" || otherMode({ mode: "standalone", label_zh: "脱机" }) !== "tethered") throw "目标模式";
  // 两段式确认：先 false，needs_confirm 弹卡，确认后 true
  calls.length = 0; let shown = "";
  const r1 = await switchMode(rpc, "standalone", async t => { shown = t; return true; });
  if (!r1.ok || shown !== CONFIRM_TEXT || CONFIRM_TEXT !== "脱机后断开主机即可上电运行，心跳丢失不再停车") throw "确认卡文案";
  if (JSON.stringify(calls) !== JSON.stringify([["set_run_mode", { mode: "standalone", confirmed: false }], ["set_run_mode", { mode: "standalone", confirmed: true }]])) throw "调用顺序 " + JSON.stringify(calls);
  calls.length = 0; const r2 = await switchMode(rpc, "standalone", async () => false);
  if (!r2.cancelled || calls.length !== 1) throw "取消后不发 confirmed=true";
  const r3 = await switchMode(bad, "standalone", async () => true); if (!r3.disable || !r3.note!.includes("set_run_mode")) throw "接口不可用";
  // Agent 只能跳转：set_run_mode 的入口是 jump，不替用户点
  if (!ACTIONS.set_run_mode.jump || ACTIONS.set_run_mode.step !== "封箱" || resolveFix("set_run_mode", () => true)?.label !== "前往封箱") throw "Agent 只给跳转";
  // 急停 / 自检：只用侧车 message_zh
  if (estopMessage({ estop_cause: { cause: "hb", message_zh: "心跳超时 1.0 s，已停车" } }) !== "心跳超时 1.0 s，已停车" || estopMessage({}) !== null) throw "estop";
  const f = selftestFailures({ selftest: { pass: false, failed_items: [{ code: "enc", key: "enc_a", message_zh: "左轮编码器无脉冲" }], t: 1 } });
  if (f.join() !== "左轮编码器无脉冲" || selftestFailures({ selftest: null }).length || selftestFailures({ selftest: { pass: true, failed_items: [] } }).length) throw "selftest";
  console.log("boardstate ok");
})().catch(e => { console.error(e); process.exit(1); });
// run_selftest 错误（mock 本地服务回包）
void (async () => {
  const mock = (code: string) => Promise.reject({ code, message: "x", fix_action: code === "no_board" ? "connect" : undefined });
  const v1 = await mock("no_board").catch(selftestErrView);
  if (v1.text !== "未连接板子" || v1.btn?.label !== "连接" || v1.btn.action !== "connect") throw "no_board 视图";
  const v2 = await mock("selftest_timeout").catch(selftestErrView);
  if (v2.text !== "自检超时" || v2.btn?.label !== "重试" || v2.btn.action !== "retry") throw "selftest_timeout 视图";
  const v3 = selftestErrView({ code: "other", message: "原因", fix: "处理" });
  if (v3.text !== "原因 · 处理" || v3.btn) throw "其它错误照写原因";
  console.log("selftest err ok");
})().catch(e => { console.error(e); process.exit(1); });
// 封箱页只读自检项（mock 本地服务自检快照）：提示只看 stale，不推算
{
  const f = (t: number) => String(t);
  const ok = { pass: true, failed_items: [], t: 5 };
  const none = sealSelftestView({}, null, f);
  if (none.need || none.text !== "尚未自检") throw "没自检：只显示，不提示";
  const bad = sealSelftestView({ selftest: { pass: false, failed_items: [{ code: "imu", key: "imu", message_zh: "IMU 无响应" }], t: 5 } }, 1000, f);
  if (!bad.need || bad.text !== "自检未通过" || bad.when !== "1000") throw "未通过要提示";
  const old = sealSelftestView({ selftest: ok, params_hash: "h2" } as any, 1000, f);   // 字段未上线：哈希变了也不推算
  if (old.need || old.when !== "1000") throw "无 stale 时不提示 " + JSON.stringify(old);
  const fresh = sealSelftestView({ selftest: { ...ok, at: 1_700_000_000, params_hash_at: "h1", stale: false } } as any, 1000, f);
  if (fresh.need || fresh.when !== "1700000000000") throw "stale=false 不提示，时间用 at " + JSON.stringify(fresh);
  const stale = sealSelftestView({ selftest: { ...ok, at: 1_700_000_000_000, params_hash_at: "h1", stale: true } } as any, 1000, f);
  if (!stale.need || stale.when !== "1700000000000") throw "stale=true 要提示";
  if (RESELFTEST !== "请重新自检") throw "文案";
  console.log("seal selftest ok");
}
