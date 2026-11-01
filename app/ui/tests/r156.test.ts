import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { wsUrlFor, WS_F, improvementOf, IMPROVE_F } from "../src/fieldmap";
import { resultCardHtml, type Stopped } from "../src/iterui";
const esc = (s: string) => String(s).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);
const L = (protocol: string, hostname: string, port: string, search = "") => ({ protocol, hostname, port, search });
// #156 侧车提供页面：同主机、ws 端口 = 页面端口 - 1（非默认端口）
assert.equal(wsUrlFor(L("http:", "127.0.0.1", "18952")), "ws://127.0.0.1:18951");
assert.equal(wsUrlFor(L("http:", "192.168.1.7", "40002")), "ws://192.168.1.7:40001");
assert.equal(wsUrlFor(L("https:", "box.local", "9443")), "wss://box.local:9442");
assert.equal(wsUrlFor(L("http:", "::1", "18952")), "ws://[::1]:18951");
assert.equal(wsUrlFor(L("http:", "127.0.0.1", "18952", "?ws=ws://h:1")), "ws://h:1", "?ws= 优先");
// Tauri / vite 开发 / file: 退回 8765
for (const l of [L("tauri:", "localhost", ""), L("https:", "tauri.localhost", ""), L("http:", "tauri.localhost", "80"), L("file:", "", "")]) assert.equal(wsUrlFor(l), WS_F.fallback);
assert.equal(wsUrlFor(L("http:", "localhost", "5173"), true), WS_F.fallback);
assert.equal(WS_F.fallback, "ws://127.0.0.1:8765");
const src = readFileSync("src/main.ts", "utf8"); assert.match(src, /new Link\(wsUrlFor\(location/);
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
