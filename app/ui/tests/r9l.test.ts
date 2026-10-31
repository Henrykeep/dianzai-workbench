import assert from "node:assert";
import { readFileSync } from "node:fs";
import { setRoleCodes, roleCodes } from "../src/rolecodes";
import { roleCellHtml, collectRoles, roleLabel } from "../src/roles";
import { retestBlock, resultCardHtml } from "../src/iterui";
// roles.json：v1 用文件里的 zh 显示、回传 code；版本不认识 / 没文件 → 兜底表
const fb = roleCodes().map(x => x[0]).join();
let file: any; try { file = JSON.parse(readFileSync("../../docs/dev/roles.json", "utf8")); } catch { file = { schema_version: 1, roles: [{ code: "P", zh: "比例项" }, { code: "NEWX", zh: "新角色" }] }; }
setRoleCodes(file);
const req = { missing: ["g1"], suggested: {}, reason: "" };
for (const r of file.roles) { const h = roleCellHtml("g1", req); assert.ok(h.includes(`value="${r.code}"`) && h.includes(`>${r.zh}<`), r.code); assert.equal(roleLabel(r.code), r.zh); }
const last = file.roles[file.roles.length - 1].code;
assert.deepEqual(collectRoles(req, { g1: last }), { g1: last });
setRoleCodes({ schema_version: 2, roles: [{ code: "Q", zh: "怪" }] }); assert.equal(roleCodes().map(x => x[0]).join(), fb);
setRoleCodes(null); assert.equal(roleCodes().map(x => x[0]).join(), fb);
assert.equal(collectRoles(req, { g1: "NEWX" }), null);
// limit_name：链接带声明路径；没给就用 max_step
const p: any = { amp_reduced: true, amp_spec: 1, amp_tested: 0.5, verdict: { v: "partial", warn: "未验题面幅度" }, best: { params: { a: 1 }, metrics: {} } };
const b = { reason: "step_too_large", limit: 0.6, limit_unit: "m", fix_action: "edit_declaration" };
assert.equal(retestBlock({ ...p, retest_blocked_by: { ...b, limit_name: "link.params.g1.max_step" } })!.key, "link.params.g1.max_step");
assert.match(resultCardHtml({ ...p, retest_blocked_by: { ...b, limit_name: "link.params.g1.max_step" } }, s => s, { canApply: true, applyReady: true }), /data-field="link\.params\.g1\.max_step"/);
assert.equal(retestBlock({ ...p, retest_blocked_by: b })!.key, "max_step");
const main = readFileSync("src/main.ts", "utf8");
assert.match(main, /x\.dataset\.declKey === key/);
console.log("r9l ok");
