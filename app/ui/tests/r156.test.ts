import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { wsUrlFor, WS_F, inconclusiveOf, INCONCL_F } from "../src/fieldmap";
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
// #158 不确定：通用映射
const M = "数据噪声大，无法确认比初值好，建议保留初值或加长采样后重测";
assert.deepEqual(inconclusiveOf({ improvement: "inconclusive", message_zh: M }), { msg: M });
assert.deepEqual(inconclusiveOf({ kept_initial: true, kept_initial_reason: M }), { msg: M });
assert.deepEqual(inconclusiveOf({ verdict: { improvement: "inconclusive", message_zh: M } }), { msg: M });
assert.deepEqual(inconclusiveOf({ improvement: "inconclusive" }), { msg: INCONCL_F.fallbackZh });
assert.equal(inconclusiveOf({ improvement: "improved" }), null); assert.equal(inconclusiveOf({ kept_initial: false }), null);
const r = { reason: "pass", run_id: "Z", improvement: "inconclusive", message_zh: M, best: { iter: 1, params: { kp: 4 } }, base: { overshoot_pct: 30, settling_s: 0.9 }, metrics: { overshoot_pct: 28, settling_s: 0.85 } };
const h = resultCardHtml(r as any as Stopped, esc, { canApply: true, applyReady: true });
assert.match(h, new RegExp(M)); assert.match(h, /未确认改善/);
assert.doesNotMatch(h, /已改善|改善了|更好|达标/);
assert.doesNotMatch(h, /class="it-verdict pass"/);
const keep = h.indexOf('id="it-keep"'), wr = h.indexOf('id="it-write"');
assert.ok(keep > 0 && wr > keep, "保留初值在前");
assert.match(h, /id="it-keep">保留初值/); assert.match(h, /variant="brand" size="small" id="it-keep"/);
assert.match(h, /appearance="outlined" size="small" id="it-write" data-confirm2="1"/);
assert.match(src, /dataset\.confirm2 === "1" && w\.dataset\.armed !== "1"/);
// 正常结果不受影响
const ok = resultCardHtml({ ...r, improvement: undefined, message_zh: undefined } as any as Stopped, esc, { canApply: true, applyReady: true });
assert.doesNotMatch(ok, /it-keep/);
console.log("r156 ok");
