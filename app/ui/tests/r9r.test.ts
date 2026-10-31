import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { boardIdOf, shortUid, sameBoard, uidChipHtml, conflictOf, fromHello, fromBlockers, conflictBannerHtml, lockSchemaIn, SCHEMA_LOCK_SEL, resultSameBoard } from "../src/boardid";
import { BOARD_UID_F, BOARD_UID_ZH, SCHEMA_CONFLICT_F } from "../src/fieldmap";
const esc = (s: string) => s.replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);
const hs = (uid: any, sup: any) => ({ [BOARD_UID_F.uid]: uid, [BOARD_UID_F.supported]: sup });
// 板子身份
assert.equal(boardIdOf({}), null);   // 旧本地服务：不提示
const ok = boardIdOf(hs("0123456789ABCDEF", true))!;
assert.equal(ok.uid, "0123456789abcdef"); assert.equal(ok.notice, ""); assert.equal(ok.short, "0123…cdef"); assert.equal(shortUid("abc"), "abc");
assert.match(uidChipHtml(ok, esc), /板 0123…cdef/); assert.match(uidChipHtml(ok, esc), /title="板子身份 0123456789abcdef"/);
const un = boardIdOf(hs("0123456789abcdef", false))!;
assert.equal(un.uid, null); assert.equal(un.notice, BOARD_UID_ZH.unsupported); assert.equal(BOARD_UID_ZH.unsupported, "此芯片暂不支持板子识别，换板检测不可用");
assert.match(uidChipHtml(un, esc), /data-uid-notice>此芯片暂不支持板子识别/);
const nr = boardIdOf(hs(null, true))!; assert.equal(nr.notice, "未读到板子身份");
assert.equal(boardIdOf(hs("xyz", true))!.notice, "未读到板子身份");   // 格式不对当未读到
assert.equal(boardIdOf({ [BOARD_UID_F.uid]: "0123456789abcdef" })!.supported, false);   // 缺 uid_supported 不算支持
// 换板判定：不支持 / 未读到永远不算同一块
assert.equal(sameBoard(un, un), null); assert.equal(sameBoard(nr, nr), null); assert.equal(sameBoard(ok, ok), true);
assert.equal(sameBoard(ok, boardIdOf(hs("ffffffffffffffff", true))), false);
assert.equal(resultSameBoard({}, true, null), true);       // 旧服务：按端口
assert.equal(resultSameBoard({}, true, un), false);        // 不支持：端口一样也不算
assert.equal(resultSameBoard({}, true, nr), false);
assert.equal(resultSameBoard({ board_uid: "0123456789ABCDEF" }, false, ok), true);
assert.equal(resultSameBoard({ board_uid: "ffffffffffffffff" }, true, ok), false);
assert.equal(resultSameBoard({}, true, ok), true);
// 结构冲突
const K = SCHEMA_CONFLICT_F;
assert.equal(conflictOf(null), null); assert.equal(conflictOf({ [K.resolved]: true }), null);
assert.deepEqual(conflictOf({ [K.msg]: "参数表版本与固件不一致", [K.fix]: "flash" }), { msg: "参数表版本与固件不一致", fix: "flash" });
assert.deepEqual(conflictOf({}), { msg: "工程与板子的结构不一致", fix: null });
assert.deepEqual(fromHello({}), { has: false, c: null }); assert.equal(fromHello({ [K.key]: null }).has, true);
assert.equal(fromHello({ [K.key]: { [K.msg]: "x" } }).c!.msg, "x");
assert.equal(fromBlockers([{ code: "estop" }]), null); assert.equal(fromBlockers(undefined), null);
assert.equal(fromBlockers([{ code: "schema_conflict", message_zh: "冲突甲", fix_action: "build" }])!.fix, "build");
assert.equal(fromBlockers([{ blocker_code: "schema_conflict", message_zh: "冲突乙" }])!.msg, "冲突乙");
const c = conflictOf({ [K.msg]: "<b>", [K.fix]: "flash" })!;
let h = conflictBannerHtml(c, { kind: "run", label: "烧录" }, esc);
assert.match(h, /结构冲突，已暂停写参数/); assert.match(h, /&#60;b&#62;/); assert.match(h, /data-sc-conflict-fix="flash">烧录<\/button>/);
h = conflictBannerHtml(c, { kind: "wait", label: "烧录", note: "等待固件支持" }, esc); assert.match(h, /disabled title="等待固件支持">烧录/);
assert.doesNotMatch(conflictBannerHtml(conflictOf({})!, null, esc), /<button/);
// 写入禁用：含提交卡「确认提交」；解开后恢复原状；不解开急停锁存
assert.ok(SCHEMA_LOCK_SEL.includes('button[data-cc="ok"]') && SCHEMA_LOCK_SEL.includes("#p-send") && SCHEMA_LOCK_SEL.includes("#it-write"));
const mk = (disabled: boolean, title = "", ds: any = {}) => ({ disabled, title, dataset: ds });
const a = mk(false, "下发"), b = mk(true, "无改动"), e = mk(true, "急停", { estop: "1" });
const root: any = { querySelectorAll: (sel: string) => sel === SCHEMA_LOCK_SEL ? [a, b, e] : [a, b, e].filter(x => "sconf" in x.dataset) };
lockSchemaIn(root, true); lockSchemaIn(root, true);
assert.ok(a.disabled && b.disabled && e.disabled); assert.match(a.title, /结构冲突未解决/);
lockSchemaIn(root, false);
assert.equal(a.disabled, false); assert.equal(a.title, "下发"); assert.equal(b.disabled, true); assert.equal(b.title, "无改动"); assert.equal(e.disabled, true);
assert.ok(!("sconf" in a.dataset));
// 接线：main.ts 三个来源 + index.html 有横幅和设备信息位
const m = readFileSync("src/main.ts", "utf8"), ix = readFileSync("index.html", "utf8");
assert.match(m, /boardId = boardIdOf\(h\)/); assert.match(m, /case SCHEMA_CONFLICT_F.key:/); assert.match(m, /fromBlockers\(\(m as any\)\.blockers\)/); assert.match(m, /fromBlockers\(p\.blockers\)/);
assert.match(m, /resultSameBoard\(res,/);
assert.match(ix, /id="sconf-banner"/); assert.match(ix, /id="ro-uid"/);
// 字段名只在 fieldmap
for (const f of ["src/boardid.ts", "src/main.ts"]) assert.doesNotMatch(readFileSync(f, "utf8"), /"(board_uid|uid_supported|schema_conflict|message_zh)"/);
console.log("r9r ok");
