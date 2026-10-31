import assert from "node:assert";
import { readFileSync } from "node:fs";
import { resultCardHtml, stopReasonZh, partialConfirmZh, ampSpecValue, REASON_ZH } from "../src/iterui";
import { ampLine, STOP_F } from "../src/fieldmap";
import { RoleSender, roleCardHtml, roleReply } from "../src/roles";
const esc = (s: string) => s;
(async () => {
// #142 回错很快：0.3 s 连点 5 次只发 1 次；回错后按钮灰着；文案带「后端拒绝：」
const tx = new RoleSender(); let sent = 0; const roles = { kp: "P" };
const fast = async () => { sent++; return { message_zh: "不认这个角色", fix_action: "confirm_roles" }; };
let u: any = null;
for (let i = 0; i < 5; i++) { const r = await tx.send(roles, fast); if (r) u = r; await new Promise(z => setTimeout(z, 300)); }
assert.equal(sent, 1);
assert.match(u.msg, /^后端拒绝：不认这个角色/);
const req = { missing: ["kp"], suggested: {}, reason: "" };
assert.match(roleCardHtml(req, u), /id="role-ok" disabled/);
assert.doesNotMatch(roleCardHtml(req, { ...u, same: false }), /id="role-ok" disabled/);
assert.ok(tx.canSend({ kp: "I" })); await tx.send({ kp: "I" }, fast); assert.equal(sent, 2);
assert.equal(roleReply({ ok: true, roles }).phase, "sent");
// #141 降幅卡：主按钮复测，采用是次要按钮且要确认
const part: any = { reason: "budget_rounds", amp_reduced: true, amp_spec: 1, amp_tested: 0.5, verdict: { v: "partial", warn: "未验题面幅度" }, best: { params: { a: 1 }, metrics: {} } };
const h = resultCardHtml(part, esc, { canApply: true, applyReady: true });
assert.match(h, /variant="brand"[^>]*id="it-rerun">按题面幅度复测/);
assert.doesNotMatch(h, /variant="brand"[^>]*id="it-write"/);
assert.doesNotMatch(h, />采用这组参数</);
assert.equal(ampSpecValue(part), 1);
assert.match(partialConfirmZh(part), /只在 0\.5 幅度上验证过，未验题面幅度/);
const main = readFileSync("src/main.ts", "utf8");
assert.match(main, /window\.confirm\(partialConfirmZh/);
assert.doesNotMatch(main.slice(main.indexOf("#it-rerun"), main.indexOf("$(\"it-go\").onclick")), /verified|已验证档"/);
// #140 有 amp_unit 才带单位；没有不猜
assert.equal(ampLine({ ...part, amp_unit: "m" }), "题面幅度 1 m，实测幅度 0.5 m");
assert.equal(ampLine({ ...part, target: { unit: "rpm" } }), "题面幅度 1，实测幅度 0.5");
// #139 后端 reason 枚举（events.md / iterate.py，只读）+ 前端认识的代码，全都要有中文
const ev = readFileSync("../../docs/dev/events.md", "utf8");
const line = ev.split("\n").find(l => l.includes("iterate.stopped") && l.includes("`reason` ∈"))!;
assert.ok(line, "events.md 里找不到 iterate.stopped 的 reason 枚举");
const codes = new Set(line.split("`reason` ∈")[1].split("（")[0].split("/").map(x => x.trim().replace(/[^a-z_].*$/, "")).filter(Boolean));
for (const m of readFileSync("../sidecar/dzbench/agent/iterate.py", "utf8").matchAll(/_stopped\("([a-z_]+)"/g)) codes.add(m[1]);
for (const c of [...STOP_F.divCodes, ...STOP_F.abortCodes, ...STOP_F.invalidCodes]) codes.add(c);
assert.ok(codes.has("diverged") && codes.size >= 10);
for (const c of codes) { const z = stopReasonZh({ reason: c } as any, []); assert.doesNotMatch(z, /其他（|[a-z_]{4,}/, `${c} → ${z}`); }
assert.ok(REASON_ZH.diverged);
// reason_codes.json：每个代码都显示文件里的 zh；未知代码「未知原因」
const { setReasonCodes } = await import("../src/reasoncodes");
let file: any; try { file = JSON.parse(readFileSync("../../docs/dev/reason_codes.json", "utf8")); } catch { file = { diverged: { zh: "响应发散", kind: "diverged" }, new_code_x: { zh: "新原因", kind: "abort" } }; }
setReasonCodes(file);
for (const [c, v] of Object.entries<any>(file)) if (![...STOP_F.abortCodes, ...STOP_F.invalidCodes].includes(c as any)) assert.equal(stopReasonZh({ reason: c } as any, []), v.zh);
assert.equal(stopReasonZh({ reason: "zz_not_a_code" } as any, []), "未知原因");
setReasonCodes(null);
assert.equal(stopReasonZh({ reason: "zz_not_a_code" } as any, []), "未知原因");
console.log("r9k ok", codes.size);
})().catch(e => { console.error(e); process.exit(1); });
