import assert from "node:assert";
import { readFileSync } from "node:fs";
import { setRoleCodes, roleCodesNotice, roleCodesStatus } from "../src/rolecodes";
import { setReasonCodes, reasonCodesNotice } from "../src/reasoncodes";
import { roleCardHtml } from "../src/roles";
const req = { missing: ["g1"], suggested: {}, reason: "" };
const card = () => roleCardHtml(req, { phase: "idle", left: 1 });
// 角色表：缺失 / 版本不对 / 坏格式 → 卡里有提示（缺失与格式错分开说）；合格 → 没有
setRoleCodes(null); assert.match(card(), /角色表缺失，已使用内置列表。修复：运行 python -m dzbench selfcheck-data/);
setRoleCodes({ schema_version: 2, roles: [{ code: "P", zh: "比例" }] }); assert.match(card(), /角色表格式错误，已使用内置列表/);
setRoleCodes({ schema_version: 1, roles: [{ code: "P" }] }); assert.match(card(), /角色表格式错误/);
setRoleCodes("garbage"); assert.equal(roleCodesStatus(), "bad");
setRoleCodes({ schema_version: 1, roles: [{ code: "P", zh: "比例" }] }); assert.equal(roleCodesNotice(), ""); assert.doesNotMatch(card(), /role-data/);
// 原因表
setReasonCodes(null); assert.match(reasonCodesNotice(), /^原因表缺失，已使用内置列表。修复：运行 python -m dzbench selfcheck-data$/);
setReasonCodes([1, 2]); assert.match(reasonCodesNotice(), /原因表格式错误/);
setReasonCodes({ a: { zh: "甲" }, b: { kind: "x" } }); assert.match(reasonCodesNotice(), /原因表格式错误/);
setReasonCodes({ a: { zh: "甲", kind: "abort" } }); assert.equal(reasonCodesNotice(), "");
// 状态栏只有一处，启动设一次
const html = readFileSync("index.html", "utf8"), main = readFileSync("src/main.ts", "utf8");
assert.equal(html.match(/id="ro-data"/g)?.length, 1);
assert.equal(main.match(/reasonCodesNotice\(\)/g)?.length, 1);
console.log("r9m ok");
