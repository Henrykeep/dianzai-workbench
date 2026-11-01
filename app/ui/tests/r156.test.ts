import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { wsUrlFor, wsFromPort, wsDownZh, WS_F, improvementOf, IMPROVE_F, tuningNotesOf } from "../src/fieldmap";
import { setReasonCodes } from "../src/reasoncodes";
import { validReasons } from "../src/datatables";
import { resultCardHtml, type Stopped } from "../src/iterui";
const esc = (s: string) => String(s).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);
const L = (protocol: string, hostname: string, port: string, search = "") => ({ protocol, hostname, port, search });
// #156 侧车提供页面：同主机、ws 端口 = 页面端口 - 1（非默认端口）
void (async () => {
const U = async (l: any, d: any = {}) => (await wsUrlFor(l, d));
const P = (u: string) => (wsFromPort(L("http:", "127.0.0.1", "1"), false), u);
assert.deepEqual(wsFromPort(L("http:", "127.0.0.1", "18952")), { url: "ws://127.0.0.1:18951", src: "port" });
assert.equal(wsFromPort(L("http:", "192.168.1.7", "40002")).url, "ws://192.168.1.7:40001");
assert.equal(wsFromPort(L("https:", "box.local", "9443")).url, "wss://box.local:9442");
assert.equal(wsFromPort(L("http:", "::1", "18952")).url, "ws://[::1]:18951");
for (const l of [L("tauri:", "localhost", ""), L("https:", "tauri.localhost", ""), L("http:", "tauri.localhost", "80"), L("file:", "", "")]) assert.deepEqual(wsFromPort(l), { url: WS_F.fallback, src: "fallback" });
assert.deepEqual(wsFromPort(L("http:", "localhost", "5173"), true), { url: WS_F.fallback, src: "fallback" });
// 顺序：?ws= > meta > config.json > 端口推算 > 默认
const calls: string[] = [];
const cfg = (body: any, status = 200, delay = 0) => async (u: string, o: any) => { calls.push(u); if (delay) await new Promise((res, rej) => { const t = setTimeout(res, delay); o?.signal?.addEventListener("abort", () => { clearTimeout(t); rej(new Error("abort")); }); }); return { ok: status < 300, status, json: async () => typeof body === "string" ? JSON.parse(body) : body } as any; };
const H = L("http:", "127.0.0.1", "25742");
assert.deepEqual(await U(L("http:", "127.0.0.1", "25742", "?ws=ws://h:1"), { meta: "ws://m:2", fetch: cfg({ ws_url: "ws://c:3" }) }), { url: "ws://h:1", src: "query" });
assert.deepEqual(await U(H, { meta: "ws://m:2", fetch: cfg({ ws_url: "ws://c:3" }) }), { url: "ws://m:2", src: "meta" });
calls.length = 0;
assert.deepEqual(await U(H, { meta: "", fetch: cfg({ ws_url: "ws://c:3" }) }), { url: "ws://c:3", src: "config" }); assert.deepEqual(calls, [WS_F.config]);
assert.deepEqual(await U(H, { fetch: cfg({}, 404) }), { url: "ws://127.0.0.1:25741", src: "port" }, "404 忽略");
assert.deepEqual(await U(H, { fetch: cfg("{bad") }), { url: "ws://127.0.0.1:25741", src: "port" }, "坏 JSON 忽略");
assert.deepEqual(await U(H, { fetch: cfg({ ws_url: "http://x" }) }), { url: "ws://127.0.0.1:25741", src: "port" }, "非 ws 地址忽略");
assert.deepEqual(await U(H, { fetch: async () => { throw new Error("net"); } }), { url: "ws://127.0.0.1:25741", src: "port" });
const t0 = Date.now(); assert.deepEqual(await U(H, { fetch: cfg({ ws_url: "ws://late:1" }, 200, 5000) }), { url: "ws://127.0.0.1:25741", src: "port" }, "超时忽略");
assert.ok(Date.now() - t0 < WS_F.timeoutMs + 1500, "短超时");
assert.deepEqual(await U(L("tauri:", "localhost", ""), {}), { url: WS_F.fallback, src: "fallback" });
// 失败横幅：显示正在试的地址与来源，无写死
assert.equal(wsDownZh({ url: "ws://127.0.0.1:25741", src: "port" }), `正在连接 ws://127.0.0.1:25741（来自${WS_F.srcZh.port}），无响应`);
for (const s of Object.keys(WS_F.srcZh) as any[]) assert.ok(wsDownZh({ url: "ws://a:9", src: s })!.includes(WS_F.srcZh[s as keyof typeof WS_F.srcZh]));
assert.equal(wsDownZh(null), null);
void P;
const src = readFileSync("src/main.ts", "utf8"); assert.match(src, /new Link\(wsUrlFor\(location/); assert.match(src, /wsDownZh\(wsPick\)/); assert.match(src, /name="\$\{WS_F\.meta\}"|WS_F\.meta/);
for (const f of ["src/main.ts", "src/ws.ts"]) assert.doesNotMatch(readFileSync(f, "utf8"), /8765/, `${f} 不再写死 8765`);
// #158 improvement = confirmed | inconclusive | worse
const M = "数据噪声大，无法确认比初值好，建议保留初值或加长采样后重测";
const base = { reason: "improvement_unconfirmed", run_id: "Z", improvement: "inconclusive", message_zh: M, causes: ["采样太短", "噪声大"], default_action: "keep_initial", best: { iter: 1, params: { kp: 4 } }, base: { overshoot_pct: 30, settling_s: 0.9 } };
assert.equal(improvementOf({ improvement: "confirmed" }), null); assert.equal(improvementOf({}), null);
assert.equal(improvementOf(base)!.adopt, "confirm"); assert.equal(improvementOf({ improvement: "worse", reason: "kept_initial" })!.adopt, "none");
assert.equal(improvementOf({ improvement: "inconclusive" })!.msg, IMPROVE_F.fallbackZh);
const h = resultCardHtml(base as any as Stopped, esc, { canApply: true, applyReady: true });
assert.match(h, new RegExp(M)); assert.match(h, /未确认改善/); assert.match(h, /采样太短/);
assert.doesNotMatch(h, /已改善|改善了|更好|达标/); assert.doesNotMatch(h, /class="it-verdict pass"/);
const d = h.indexOf('id="it-default"'), wr = h.indexOf('id="it-write"');
assert.ok(d > 0 && wr > d, "主按钮在前");
assert.match(h, /variant="brand" size="small" id="it-default" data-action="keep_initial" data-decline="1">保留初值/);
assert.match(h, /appearance="outlined" size="small" id="it-write" data-confirm2="1"/);
const src2 = readFileSync("src/main.ts", "utf8");
assert.match(src2, /dataset\.confirm2 === "1" && w\.dataset\.armed !== "1"/); assert.match(src2, /#it-default/);
// worse：没有采用按钮
const w = resultCardHtml({ ...base, improvement: "worse", reason: "kept_initial", message_zh: "新参数比初值差，已保留初值" } as any as Stopped, esc, { canApply: true, applyReady: true });
assert.doesNotMatch(w, /it-write/); assert.match(w, /id="it-default"[^>]*>保留初值/); assert.match(w, /新参数比初值差/);
// 主按钮由 default_action 决定：没给 / 不认识 → 没有主按钮，绝不硬塞「保留初值」
const nd = resultCardHtml({ ...base, default_action: undefined } as any as Stopped, esc, { canApply: true, applyReady: true });
assert.doesNotMatch(nd, /it-default/); assert.match(nd, /variant="brand" size="small" id="it-write" data-confirm2/);
// 正常结果不受影响
const ok = resultCardHtml({ ...base, reason: "pass", improvement: "confirmed", message_zh: undefined, causes: undefined } as any as Stopped, esc, { canApply: true, applyReady: true });
assert.doesNotMatch(ok, /it-default|未确认改善/);
console.log("r156 ok");

// #158 后端 f5da00f 契约：improvement_info 优先；improvement_info.causes 单独显示；顶层 causes 仍是未达标诊断
{
  const card = (x: any) => resultCardHtml({ run_id: "Z", best: { iter: 1, params: { kp: 4 } }, best_card: 7, ...x } as any as Stopped, esc, { canApply: true, applyReady: true });
  const ii = { improvement: "inconclusive", reason: "improvement_unconfirmed", message_zh: "噪声大无法确认", causes: ["测量噪声大", "采样窗口偏短"], default_action: "keep_initial" };
  const g = improvementOf({ improvement: "inconclusive", causes: [{ code: "saturation", evidence: "strong" }], improvement_info: ii })!;
  assert.deepEqual(g.causes, ["测量噪声大", "采样窗口偏短"], "原因取 improvement_info.causes，不取顶层");
  assert.equal(g.def, "keep_initial"); assert.equal(g.msg, "噪声大无法确认");
  const h = card({ reason: "improvement_unconfirmed", improvement: "inconclusive", improvement_info: ii, causes: [{ code: "saturation", evidence: "strong", basis_zh: "满输出只能到六成" }] });
  assert.match(h, /id="rc-icauses"[^]*测量噪声大[^]*采样窗口偏短/); assert.match(h, /id="it-write"[^>]*data-confirm2/);
  // improvement:null → 初值已达标，未调参：中性，无采用，主按钮 keep_initial
  const un = { improvement: null, reason: null, message_zh: "初值已满足题面，本次没有改动参数", causes: [], default_action: "keep_initial" };
  const n = improvementOf({ improvement: null, improvement_info: un })!;
  assert.equal(n.head, "初值已达标，未调参"); assert.equal(n.adopt, "none"); assert.equal(n.tone, "neutral");
  assert.equal(improvementOf({ improvement: null })!.msg, "初值已达标，未调参");
  const nh = card({ reason: "pass", improvement: null, default_action: "keep_initial", improvement_info: un });
  assert.match(nh, /初值已达标，未调参/); assert.ok(!/id="it-write"/.test(nh)); assert.match(nh, /id="it-default"[^>]*keep_initial/);
  assert.match(nh, /it-verdict neutral/); assert.ok(!/id="rc-icauses"/.test(nh));
  assert.equal(improvementOf({ improvement: "confirmed", improvement_info: { improvement: "confirmed", default_action: "adopt" } }), null);
  // #159 noise_amplified_saturation：通用，按 message_zh + 前后饱和占比
  const tc = { code: "noise_amplified_saturation", sat_frac_initial: 0.82, sat_frac_best: 0.34, kd_initial: 2, kd_best: 0.5, message_zh: "初值微分过大，噪声被放大，执行器约 82% 时间饱和；已减小微分（调后约 34%）" };
  assert.deepEqual(tuningNotesOf({ tuning_causes: [tc] }, () => null), [{ code: tc.code, msg: tc.message_zh, sat: [0.82, 0.34] }]);
  const ch = card({ reason: "pass", improvement: "confirmed", tuning_causes: [tc] });
  assert.match(ch, /data-tune="noise_amplified_saturation"[^]*约 82%[^]*执行器饱和占比 82% → 34%/);
  assert.ok(!/rc-sat/.test(card({ reason: "pass", improvement: "confirmed", tuning_causes: [{ code: "noise_amplified_saturation", message_zh: "X" }] })), "无占比字段不显示");
  // 没 message_zh 时从原因表（kind tune，带 message_zh）取
  const rc = validReasons({ noise_amplified_saturation: { zh: "短", kind: "tune", message_zh: "表里的说明", causes: ["微分增益过大"] }, kept_initial: { zh: "调参未能改善，已保留初值", kind: "tune" } })!;
  assert.equal((rc as any).noise_amplified_saturation.kind, "tune"); assert.equal((rc as any).noise_amplified_saturation.message_zh, "表里的说明");
  setReasonCodes(rc);
  assert.match(card({ reason: "pass", improvement: "confirmed", tuning_causes: [{ code: "noise_amplified_saturation" }] }), /表里的说明/);
  const real = JSON.parse(readFileSync("../../docs/dev/reason_codes.json", "utf8"));
  for (const [k, v] of Object.entries<any>(real)) if (v.kind === "tune") assert.ok(validReasons(real)![k], k);
}
console.log("r156 ok");
})().catch(e => { console.error(e); process.exit(1); });
