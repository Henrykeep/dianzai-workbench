import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { boardIdOf, shortUid, sameBoard, uidChipHtml, conflictOf, fromHello, fromBlockers, conflictBannerHtml, lockSchemaIn, SCHEMA_LOCK_SEL, resultSameBoard } from "../src/boardid";
import { isClearFix } from "../src/boardid";
import { selfSummary, selfcheckHtml, parseSelf } from "../src/selfcheck";
import { clearArgs, clearResult, removedZh } from "../src/boardid";
import { SCHEMA_CLEAR_F, SELFCHECK_F } from "../src/fieldmap";
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
assert.deepEqual(conflictOf({ [K.msg]: "参数表版本与固件不一致", [K.fix]: "flash" }), { msg: "参数表版本与固件不一致", fix: "flash", files: [], hash: null, uid: null });
assert.deepEqual(conflictOf({}), { msg: "工程与板子的结构不一致", fix: null, files: [], hash: null, uid: null });
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
assert.match(m, /setBoardId\(idSrc\(h\)\)/); assert.match(m, /case SCHEMA_CONFLICT_F.key:/); assert.match(m, /fromBlockers\(\(m as any\)\.blockers\)/); assert.match(m, /fromBlockers\(p\.blockers\)/);
assert.match(m, /resultSameBoard\(res,/);
assert.match(ix, /id="sconf-banner"/); assert.match(ix, /id="ro-uid"/);
// 字段名只在 fieldmap
for (const f of ["src/boardid.ts", "src/main.ts"]) assert.doesNotMatch(readFileSync(f, "utf8"), /"(board_uid|uid_supported|schema_conflict|message_zh)"/);
// 冲突的两个文件 + 清缓存重新握手（确认卡）
const cf = conflictOf({ [K.msg]: "两份结构不一致", [K.fix]: SCHEMA_CLEAR_F.action, [K.files]: ["C:\\a\\cache\\schema.json", "boards/x/params.yaml", "多余"] })!;
assert.deepEqual(cf.files.map(f => f.path), ["C:\\a\\cache\\schema.json", "boards/x/params.yaml"]); assert.ok(isClearFix(cf));
h = conflictBannerHtml(cf, null, esc);
assert.match(h, /冲突的两个文件：<code title="C:\\a\\cache\\schema.json">schema.json<\/code> ↔ <code title="boards\/x\/params.yaml">params.yaml<\/code>/);
assert.match(h, /btn sm pri" type="button" data-sconf-clear>清除旧缓存并重新握手/); assert.doesNotMatch(h, /data-sconf-ok/);
h = conflictBannerHtml(cf, null, esc, "confirm"); assert.match(h, /data-sconf-confirm/); assert.match(h, /工程文件和板上参数不受影响/); assert.match(h, /data-sconf-ok>确认清除/); assert.match(h, /data-sconf-cancel>取消/); assert.doesNotMatch(h, /data-sconf-clear/);
assert.match(conflictBannerHtml(cf, null, esc, "busy"), /正在清除/); assert.match(conflictBannerHtml(cf, null, esc, "fail"), /data-sconf-clear.*清除失败/);
assert.deepEqual(conflictOf({ [K.files]: "x" })!.files, []);
assert.match(m, /data-sconf-ok\]"\)\?\.addEventListener\("click", \(\) => \{ sconfSt = "busy"; renderConflict\(\); void clearAndRehandshake/);
// 板子身份只来自握手：boardIdOf 只在 applyHelloIdentity 里，applyHelloIdentity 只喂 hello 的回复
assert.equal((m.match(/boardIdOf\(/g) ?? []).length, 1); assert.match(m, /function applyHelloIdentity\(h: any\) \{ setBoardId\(idSrc\(h\)\)/); assert.match(m, /function setBoardId\(src: any\) \{ (if \(!identTrusted\(src\)\) return; )?const nb = boardIdOf\(src\)/);
for (const call of m.match(/applyHelloIdentity\(\w+\);/g) ?? []) assert.equal(call, "applyHelloIdentity(h);");
assert.equal((m.match(/boardId = /g) ?? []).length, 1);
// 自检：skipped / unchecked → 琥珀「未检查」，单独计数，绝不显示全部正常
const it = (status: string) => ({ file: "roles.json", status, message_zh: "", fix_action: "" });
let sm = selfSummary({ src: "service", ok: true, items: [it("ok"), it("skipped"), it("unchecked")] });
assert.deepEqual([sm.ok, sm.bad, sm.unchecked, sm.tone], [1, 0, 2, "warn"]); assert.equal(sm.text, "自检未完成：2 项未检查");
let sh = selfcheckHtml({ src: "service", ok: true, items: [it("ok"), it("skipped")] });
assert.doesNotMatch(sh, /全部正常|自检通过/); assert.match(sh, /<tr class="sc-unchecked"><td>角色表<\/td><td>未检查/); assert.match(sh, /sc-sum-warn">自检未完成：1 项未检查/);
assert.match(selfcheckHtml({ src: "service", ok: true, items: [it("ok")] }), /sc-sum-ok">全部正常/);
sm = selfSummary({ src: "local", ok: false, items: [it("missing"), it("skipped")] }); assert.equal(sm.tone, "bad"); assert.equal(sm.text, "0 项正常，1 项有问题，1 项未检查");
assert.match(readFileSync("src/style.css", "utf8"), /\.sc-unchecked td:nth-child\(2\)\{color:var\(--warn\)/);
// Windows 自检脚本在 repo\ 下（fw-pyembed 布局）
assert.equal(SELFCHECK_F.scriptWin, "repo/app/sidecar/selfcheck_data.py");
// 最终字段：reason=schema_conflict 的冲突（含 hash / board_uid）；clear_schema_cache {hash} → {ok, removed}
const fc = fromBlockers([{ reason: "schema_conflict", hash: "abc123", board_uid: "0123456789abcdef", files: ["/x/a.json", "/y/b.json"], message_zh: "缓存旧", fix_action: "clear_schema_cache" }])!;
assert.equal(fc.hash, "abc123"); assert.equal(fc.uid, "0123456789abcdef"); assert.ok(isClearFix(fc)); assert.equal(SCHEMA_CLEAR_F.op, "clear_schema_cache");
assert.deepEqual(clearArgs(fc), { hash: "abc123" }); assert.deepEqual(clearArgs({ ...fc, hash: null }), {});
assert.deepEqual(clearResult({ ok: true, removed: ["/x/a.json", 3] }), { ok: true, removed: ["/x/a.json"] }); assert.equal(clearResult({}).ok, false);
assert.equal(removedZh(2), "已清除 2 个旧缓存文件");
assert.match(m, /clearResult\(await call\(SCHEMA_CLEAR_F\.op, c0 \? clearArgs\(c0\) : \{\}\)\); if \(!cr\.ok\) throw 0;.*await link\.rpc\("hello"\)/);
// 独立自检退出码（Tauri 包装 {exit_code, report}）：3 = 未完成，琥珀
const wrap = (code: number, items: any[]) => JSON.stringify({ exit_code: code, report: { ok: code === 0, items } });
let ps = parseSelf(wrap(3, [it("ok"), it("unchecked"), it("unchecked")]))!;
assert.equal(ps.exit, 3); assert.equal(ps.items.length, 3);
sm = selfSummary({ src: "local", ...ps }); assert.equal(sm.text, "自检未完成：2 项未检查"); assert.equal(sm.tone, "warn");
sm = selfSummary({ src: "local", ...parseSelf(wrap(3, []))! }); assert.equal(sm.tone, "warn"); assert.match(sm.text, /自检未完成/);
sm = selfSummary({ src: "local", ...parseSelf(wrap(1, [it("ok")]))! }); assert.equal(sm.tone, "bad");
sm = selfSummary({ src: "local", ...parseSelf(wrap(0, [it("ok")]))! }); assert.equal(sm.text, "全部正常");
assert.equal(parseSelf(JSON.stringify({ ok: true, items: [] }))!.exit, undefined);
const rs = readFileSync("../src-tauri/src/main.rs", "utf8"); assert.match(rs, /exit_code/); assert.match(rs, /\\"report\\":/);
console.log("r9r ok");
