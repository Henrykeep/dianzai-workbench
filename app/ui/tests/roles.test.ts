import assert from "node:assert";
import { readFileSync } from "node:fs";
import { toRoleReq, roleCellHtml, roleCardHtml, collectRoles, roleLabel } from "../src/roles";
import { ROLE_CODES, ROLE_SUGGEST_ZH, ROLE_CONFIRM_OP } from "../src/fieldmap";
const ev = { type: "iterate.stopped", reason: "needs_manual", fix_action: "confirm_roles", missing: ["a1", "b2"], suggested: { a1: "P", b2: "bogus" }, reason_zh: "有两个参数不知道是什么作用" };
const r = toRoleReq(ev)!;
assert.deepEqual(r, { missing: ["a1", "b2"], suggested: { a1: "P" }, reason: "有两个参数不知道是什么作用" });
assert.equal(toRoleReq({ result: ev })!.missing.length, 2);
assert.equal(toRoleReq({ fix_action: "retry" }), null); assert.equal(toRoleReq(null), null);
assert.deepEqual(ROLE_CODES.map(c => c[1]), ["比例", "积分", "微分", "前馈", "限幅", "其他"]);
const c1 = roleCellHtml("a1", r); assert.ok(c1.includes('value="P" selected') && c1.includes(ROLE_SUGGEST_ZH));
const c2 = roleCellHtml("b2", r); assert.ok(!c2.includes(ROLE_SUGGEST_ZH) && c2.includes("选角色"));
assert.equal(roleCellHtml("zz", r, "I"), `<span class="role-ro" title="角色（握手参数表）">积分</span>`);
assert.equal(roleCellHtml("zz", null), ""); assert.equal(roleCellHtml("zz", null, null), "");
assert.ok(roleCellHtml("zz", null, "LIM").includes("不参与整定")); assert.ok(!roleCellHtml("zz", null, "P").includes("不参与整定"));
assert.ok(roleCellHtml("q", { missing: ["q"], suggested: { q: "LIM" }, reason: "" }).includes("不参与整定"));
assert.ok(roleCardHtml(r).includes("改角色不用重新烧录")); assert.equal(roleLabel("LIM"), "限幅");
assert.ok(roleCardHtml(r).includes("有两个参数不知道是什么作用") && roleCardHtml(r).includes("确认角色"));
assert.ok(roleCardHtml(r, true).includes("重试整定") && !roleCardHtml(r, true).includes("role-ok"));
assert.equal(roleCardHtml(null), "");
assert.equal(collectRoles(r, {}), null);   // b2 没选
assert.deepEqual(collectRoles(r, { b2: "FF" }), { a1: "P", b2: "FF" });
assert.deepEqual(collectRoles(r, { a1: "D", b2: "other" }), { a1: "D", b2: "other" });
assert.equal(typeof ROLE_CONFIRM_OP, "string");
const main = readFileSync("src/main.ts", "utf8");
assert.match(main, /call\(ROLE_CONFIRM_OP, \{ roles: x \}\)/); assert.match(main, /role-miss/);
assert.doesNotMatch(readFileSync("src/roles.ts", "utf8"), /"missing"|"suggested"|"confirm_roles"/);   // 字段名只在 fieldmap
console.log("✓ roles：confirm_roles 角色确认");
