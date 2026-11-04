import { savedView, saveParams, modeGate, otherMode, switchMode, estopMessage, selftestFailures, CONFIRM_TEXT } from "../src/boardstate.ts";
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
