import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { roleReply, roleCardHtml, RoleSender, diffHtml } from "../src/roles";
import { conflictOf, conflictBannerHtml, boardIdOf, uidChipHtml } from "../src/boardid";
import { ACTIONS, resolveFix } from "../src/progress";
import { fwUnsafeOf, fromBlockersFw, ACTUATE_SEL, fwBannerHtml } from "../src/fwsafe";
import { WRITE_SEL } from "../src/batch1";
import { readableZh, BOARD_PENDING_ZH, AMP_UNIT_DECL_RE, ampLineHtml, hashTagHtml, shortHash, identTrusted } from "../src/fieldmap";
import { ledgerPick, resultCardHtml, type Stopped } from "../src/iterui";
import type { LedgerRound } from "../src/ledgerbus";
import { setReasonCodes, stopCauses } from "../src/reasoncodes";
import { validReasons } from "../src/datatables";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const main = readFileSync("src/main.ts", "utf8");

(async () => {
// 1) confirm_roles 两步（cc89c31 实测回包形状）
{
  const pv = roleReply({ ok: true, needs_confirm: true, change_id: 1, target: "/p/app.yaml", diff: "--- a\n+++ b\n@@ -1 +1 @@\n-  kp: P\n+  kp: FF", message_zh: "预览" }, { kp: "FF" });
  assert.equal(pv.phase, "preview"); assert.equal(pv.preview!.changeId, 1);
  const h = roleCardHtml({ missing: ["kp"], suggested: {}, reason: "" } as any, pv);
  assert.match(h, /id="role-commit"/); assert.match(h, /id="role-diff"/); assert.match(h, /dl-add/); assert.match(h, /dl-del/); assert.match(h, /\/p\/app\.yaml/);
  assert.match(diffHtml("+x\n-y\n@@ z"), /dl-add[\s\S]*dl-del[\s\S]*dl-hunk/);
  // 只有点了才带 change_id 发
  const sent: any[] = []; const s = new RoleSender();
  const u = await s.commit(pv.preview!, async a => { sent.push(a); return { ok: true, written: true, message_zh: "角色已写入" }; });
  assert.deepEqual(sent, [{ roles: { kp: "FF" }, confirmed: true, change_id: 1 }]); assert.equal(u!.phase, "sent"); assert.equal(u!.msg, "角色已写入");
  assert.match(main, /role-commit[\s\S]{0,400}commit\(/, "commit 只挂在确认按钮上");
  // 保护参数拒绝：reason_zh 优先；没有就 message；不静默
  const e1 = roleReply({ code: "protect_param_role", reason_zh: "max_rps 是保护参数", fix: "只能标 LIM" });
  assert.equal(e1.phase, "error"); assert.ok(e1.protect); assert.match(e1.msg!, /max_rps 是保护参数/);
  const e2 = roleReply({ code: "protect_param_role", message: "确认参数角色失败：max_rps 是保护参数（限幅）", fix: "保护参数只能标 LIM 或 other" });
  const eh = roleCardHtml({ missing: ["max_rps"], suggested: {}, reason: "" } as any, e2);
  assert.match(eh, /保护参数不能当调参角色/); assert.match(eh, /max_rps 是保护参数/); assert.match(eh, /处理：保护参数只能标 LIM/);
  assert.equal(roleReply({ ok: true, unchanged: true, message_zh: "无需改动" }).phase, "sent");
}
// 2) files [{path,kind}]：逐个标类型；build → 重新构建，reflash → 重新烧录；cache 仍走清缓存
{
  const files = [{ path: "/h/schemas/AD5791CF.json", kind: "cache" }, { path: "/w/build/host-sim/car_2wd/linkgen/link_schema.json", kind: "build" }];
  const cc = conflictOf({ code: "schema_conflict", message_zh: "冲突", fix_action: "clear_schema_cache", files })!;
  assert.deepEqual(cc.files.map(f => f.kind), ["cache", "build"]);
  const hc = conflictBannerHtml(cc, null, esc); assert.match(hc, /本机缓存/); assert.match(hc, /构建产物/); assert.match(hc, /data-sconf-clear/);
  const cb = conflictOf({ code: "schema_conflict", message_zh: "冲突", fix_action: "build", files: [files[1], { path: "/x/link_schema.json", kind: "build" }] })!;
  const hb = conflictBannerHtml(cb, resolveFix("build", () => true), esc);
  assert.match(hb, /data-sc-conflict-fix="build"[^>]*>重新构建/); assert.doesNotMatch(hb, /data-sconf-clear/);
  assert.equal(conflictOf({ fix_action: "build", fix_zh: "重新编译", files: [files[1], { path: "/m/link_schema.json", kind: "build" }] })!.fix, "build", "fix-r9c 后端按种类给 fix_action，照用");
  assert.equal(conflictOf({ fix_action: "clear_schema_cache", files: [files[1], { path: "/m/link_schema.json", kind: "build" }] })!.fix, "clear_schema_cache", "前端不再改写 fix_action");
  assert.equal(conflictOf({ fix_action: "reflash", fix_zh: "重新烧录固件" })!.fixZh, "重新烧录固件");
  assert.equal(conflictOf({ fix_action: "clear_schema_cache", files })!.fix, "clear_schema_cache");
  const c3 = conflictOf({ fix_action: "clear_schema_cache", files: [files[1], { path: "/w/build/tests/car_link/link_schema.json", kind: "build" }, files[0]] })!;
  assert.equal(c3.files.length, 3); assert.equal(c3.files[0].kind, "cache", "三份：缓存份排前、全部列出"); assert.equal(c3.fix, "clear_schema_cache");
  assert.ok(ACTIONS.reflash && ACTIONS.reflash.ui === "fw-flash");
  const cr = conflictOf({ code: "schema_conflict", fix_action: "reflash", files: ["/a/x.json", "/b/x.json"] })!;
  assert.equal(cr.files[0].kind, null, "旧版字符串照收");
  assert.match(conflictBannerHtml(cr, resolveFix("reflash", () => true), esc), /data-sc-conflict-fix="reflash"[^>]*>重新烧录/);
}
// 3) fw_estop_unsafe：事件 / error / 阻塞项都认；横幅 + 重新烧录；执行器禁，烧录/存参数/读取不禁
{
  const ev = { type: "fw_estop_unsafe", safe: false, reason: "old_fw", message_zh: "此固件存在急停可被误清除的问题，请重新烧录", fix_action: "reflash", min_version: "0.18.0", version: "0.17.2" };
  const u = fwUnsafeOf(ev)!; assert.equal(u.fix, "reflash");
  const b = fwBannerHtml(u, esc); assert.match(b, /急停可被误清除/); assert.match(b, /data-fwsafe-fix="reflash"[^>]*>重新烧录/); assert.match(b, /0\.18\.0/);
  assert.ok(fwUnsafeOf({ type: "error", code: "fw_estop_unsafe", message: "x" }));
  assert.ok(fromBlockersFw([{ code: "fw_estop_unsafe" }])); assert.equal(fwUnsafeOf({ ...ev, safe: true }), null);
  assert.doesNotMatch(ACTUATE_SEL, /#fw-flash\b|#tb-save\b|#pre-bbtn\b/); assert.match(WRITE_SEL, /#fw-flash/);
  assert.ok(ACTUATE_SEL.split(",").length > 3);
  assert.match(main, /case FW_ESTOP_F\.key/); assert.match(main, /fromBlockersFw/);
}
// 4) amp_unit_decl → link.telemetry.fields[].unit
{
  // #153 只用后端的键；没给 → data-decl-unit 空（只打开项目页），不拼、不用 link.step.unit
  assert.match(ampLineHtml({ amp_reduced: true, amp_spec: 2, amp_tested: 1, amp_unit: null, amp_unit_decl: null, y: "speed" }, esc), /data-decl-unit=""/);
  assert.ok(AMP_UNIT_DECL_RE.test("link.telemetry.fields[name=spd_a].unit"));
  for (const f of ["src/fieldmap.ts", "src/main.ts"]) assert.doesNotMatch(readFileSync(f, "utf8"), /link\.step\.unit/);
  assert.match(main, /if \(!key\) return;/); assert.match(main, /key\.includes\("\["\) \? undefined/);
  assert.match(ampLineHtml({ amp_reduced: true, amp_spec: 2, amp_tested: 1, amp_unit: null, amp_unit_decl: "link.telemetry.fields[name=y].unit" }, esc), /fields\[name=y\]/);
}
// 5) #147 round_id / params_hash 对轮 + 短 hash
{
  assert.equal(shortHash("0123456789abcdef"), "01234567");
  assert.match(hashTagHtml({ params_hash: "0123456789abcdef" }, esc), /#01234567/);
  const rs: LedgerRound[] = [
    { n: 2, params: { kp: 1 }, metrics: { overshoot_pct: 99 }, valid: true, runId: "r", paramsHash: "aaaa" },
    { n: 2, params: { kp: 2 }, metrics: { overshoot_pct: 3 }, valid: true, runId: "r", paramsHash: "bbbb" },
  ];
  const p = ledgerPick({ best: { iter: 2, params: { kp: 2 }, params_hash: "bbbb" } } as any as Stopped, rs);
  assert.equal(p.best!.metrics!.overshoot_pct, 3, "按 params_hash 对轮");
}
// 6) board_ident_source 不是 handshake → 忽略
{
  assert.ok(identTrusted({ board_uid: "x", board_ident_source: "handshake" })); assert.ok(identTrusted({ board_uid: "x" }));
  assert.equal(identTrusted({ board_uid: "x", board_ident_source: "guess" }), false);
  assert.match(main, /if \(!identTrusted\(src\)\) return/);
}
// 7) 新原因码（对象无响应）：原因表通用渲染 + causes + 已停止输出
{
  const tab = { no_improve: { zh: "连续 3 轮没有改进", kind: "stop" }, object_unresponsive: { zh: "对象无响应", kind: "stop", causes: ["电机未上电", "编码器线松"], stop: true } };
  assert.ok(validReasons(tab)!.object_unresponsive.causes!.length === 2);
  setReasonCodes(tab);
  const r: any = { type: "iterate.stopped", reason: "object_unresponsive", rounds: 1, verdict: { v: "fail" } };
  assert.deepEqual(stopCauses(r), { causes: ["电机未上电", "编码器线松"], stopped: true });
  const h = resultCardHtml(r, esc, { canApply: false, applyReady: false });
  assert.match(h, /对象无响应/); assert.match(h, /可能原因：/); assert.match(h, /电机未上电/); assert.match(h, /已停止输出/); assert.doesNotMatch(h, /object_unresponsive/);
  const r2: any = { reason: "brand_new_code", causes: ["输出饱和", { zh: "负载卡死" }, "no_improve"], output_stopped: true };
  assert.deepEqual(stopCauses(r2), { causes: ["输出饱和", "负载卡死", "连续 3 轮没有改进"], stopped: true });
  assert.equal(stopCauses({ reason: "no_improve" }).stopped, false);
}
// #151 pending
{
  const b = boardIdOf({ board_uid: null, uid_supported: null, board_ident_source: "pending" })!;
  assert.ok(b.pending); assert.equal(b.notice, BOARD_PENDING_ZH);
  const h = uidChipHtml(b, esc); assert.match(h, /正在识别板子…/); assert.doesNotMatch(h, /不支持/);
  assert.ok(identTrusted({ board_ident_source: "pending" }));
  assert.match(uidChipHtml(boardIdOf({ uid_supported: false, board_ident_source: "handshake" }), esc), /不支持/);
}
// #150 版本 None
{
  assert.equal(readableZh("版本 None 本地服务不认识"), "缺少版本号（文件可能已损坏，请重新安装） 本地服务不认识");
  assert.doesNotMatch(readableZh("x None y"), /None/); assert.equal(readableZh("Nonexistent"), "Nonexistent");
}
// #154 run_id + 轮号同时对上
{
  const rs: LedgerRound[] = [
    { n: 1, params: { kp: 1 }, metrics: { overshoot_pct: 50 }, valid: true, runId: "uuid-A", roundId: "1" },
    { n: 1, params: { kp: 2 }, metrics: { overshoot_pct: 4 }, valid: true, runId: "uuid-B", roundId: "1" },
  ];
  const p = ledgerPick({ run_id: "uuid-B", best: { iter: 1, params: { kp: 2 }, round_id: "1" } } as any as Stopped, rs);
  assert.equal(p.best!.metrics!.overshoot_pct, 4, "同轮号不同 run 不串");
}
console.log("r10w ok");
})().catch(e => { console.error(e); process.exit(1); });
