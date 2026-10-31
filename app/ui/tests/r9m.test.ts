import assert from "node:assert";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { ROLES_T, setRoleCodes, roleCodes, roleCodesNotice } from "../src/rolecodes";
import { REASONS_T, reasonCodesNotice, reasonZh } from "../src/reasoncodes";
import { buildCheck, DataTable, validRoles, REQUIRE_REASON_CODES } from "../src/datatables";
import { roleCardHtml } from "../src/roles";
import { reasonStatusText } from "../src/fieldmap";
const raw = readFileSync("../../docs/dev/roles.json", "utf8"), sha = createHash("sha256").update(raw).digest("hex");
const req = { missing: ["g1"], suggested: {}, reason: "" };
const card = () => roleCardHtml(req, { phase: "idle", left: 1 });
// 构建闸门
assert.deepEqual(buildCheck(raw, null), []);                                   // 真 roles.json 合格；原因表缺失暂时放行
assert.deepEqual(buildCheck(null, null), ["docs/dev/roles.json 缺失"]);
assert.deepEqual(buildCheck('{"schema_version":2,"roles":[]}', null), ["docs/dev/roles.json 格式错误"]);
assert.deepEqual(buildCheck("{bad", null), ["docs/dev/roles.json 格式错误"]);
assert.deepEqual(buildCheck(raw, '{"x":{}}'), ["docs/dev/reason_codes.json 格式错误"]);   // 原因表在就必须合格
assert.deepEqual(buildCheck(raw, null, true), ["docs/dev/reason_codes.json 缺失"]);        // 开关打开后缺失也红
assert.equal(REQUIRE_REASON_CODES, false);   // TODO：reason_codes.json 进仓库后改成 true（datatables.ts 一处）
assert.match(readFileSync("vite.config.ts", "utf8"), /buildCheck\(roles, reasons\)[\s\S]*throw new Error/);
// 握手之前：不提示
setRoleCodes(JSON.parse(raw), sha); ROLES_T.reset();
assert.equal(roleCodesNotice(), ""); assert.doesNotMatch(card(), /role-data/);
// 握手没带数据表 → 用打包副本 + 提示
ROLES_T.onHandshake({ hash: "h" }); assert.equal(roleCodesNotice(), "侧车未提供角色表，已使用界面内置列表"); assert.match(card(), /侧车未提供角色表/);
assert.equal(roleCodes().length, validRoles(raw)!.length);
// 握手带了且 sha 一致 → 用侧车内容，无提示（content 可以是对象或 JSON 字符串）
ROLES_T.onHandshake({ data_tables: { roles: { sha256: sha.toUpperCase(), content: raw } } }); assert.equal(roleCodesNotice(), ""); assert.doesNotMatch(card(), /role-data/);
// sha 不一致 → 提示，仍用侧车内容
ROLES_T.onHandshake({ data_tables: { roles: { sha256: "00", content: { schema_version: 1, roles: [{ code: "X", zh: "新" }] } } } });
assert.equal(roleCodesNotice(), "界面与侧车角色表不一致，请重装或更新"); assert.deepEqual(roleCodes(), [["X", "新"]]);
// 侧车内容不合格（版本 / 缺 zh / 乱码）→ 打包副本 + 提示
for (const c of [{ schema_version: 2, roles: [{ code: "P", zh: "比例" }] }, { schema_version: 1, roles: [{ code: "P" }] }, "{oops"]) {
  ROLES_T.onHandshake({ data_tables: { roles: { sha256: sha, content: c } } });
  assert.match(roleCodesNotice(), /^侧车角色表格式错误，已使用界面内置列表。修复：运行 python -m dzbench selfcheck-data$/); assert.equal(roleCodes().length, validRoles(raw)!.length);
}
ROLES_T.reset(); assert.equal(roleCodesNotice(), "");
// 原因表：同样几种情况；打包里没有文件时，「缺失」只在开发模式提示
REASONS_T.setBundled(null); REASONS_T.reset(); assert.equal(reasonCodesNotice(true), "");
REASONS_T.onHandshake({}); assert.equal(reasonCodesNotice(false), "侧车未提供原因表，已使用界面内置列表");
assert.equal(reasonStatusText(reasonCodesNotice(false)), "侧车未提供原因表，已用内置列表 · 修复：python -m dzbench selfcheck-data");
REASONS_T.onHandshake({ data_tables: { reason_codes: { sha256: "ab", content: { diverged: { zh: "发散了", kind: "diverged" } } } } });
assert.equal(reasonCodesNotice(false), ""); assert.equal(reasonCodesNotice(true), "界面打包里没有原因表（仅开发模式提示）"); assert.equal(reasonZh("diverged", {}), "发散了");
REASONS_T.setBundled({ diverged: { zh: "发散" } }, "cd"); REASONS_T.onHandshake({ data_tables: { reason_codes: { sha256: "ab", content: { diverged: { zh: "发散了" } } } } });
assert.equal(reasonCodesNotice(), "界面与侧车原因表不一致，请重装或更新"); assert.equal(reasonStatusText(reasonCodesNotice()), "界面与侧车原因表不一致，请重装或更新");
REASONS_T.onHandshake({ data_tables: { reason_codes: { sha256: "cd", content: [1] } } }); assert.match(reasonCodesNotice(), /^侧车原因表格式错误/); assert.equal(reasonZh("diverged", {}), "发散");
REASONS_T.setBundled(null); REASONS_T.reset();
// 生产包不带开发提示：DEV 来自 import.meta.env
assert.match(readFileSync("src/reasoncodes.ts", "utf8"), /import\.meta as any\)\.env\?\.DEV/);
void DataTable;
// 状态栏一处、16px
const html = readFileSync("index.html", "utf8"), main = readFileSync("src/main.ts", "utf8");
assert.equal(html.match(/id="ro-data"/g)?.length, 1);
assert.match(readFileSync("src/style.css", "utf8"), /#ro-data\{[^}]*font-size:16px/);
assert.match(main, /ROLES_T\.onHandshake\(s\); REASONS_T\.onHandshake\(s\)/);
assert.doesNotMatch(main.replace(/^.*fieldmap.*$/gm, ""), /"data_tables"/);
console.log("r9m ok");
