import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { linkTag } from "../src/batch1";
import { linkView } from "../src/linkmsg";
import { actGateOf, deferredOf, fromBlockersGate, codeOf, isGateCode, gateBannerHtml, durCapNoteHtml, reasonText } from "../src/actgate";
import { boardIdOf } from "../src/boardid";
import { resultCardHtml, type Stopped } from "../src/iterui";
import { setReasonCodes } from "../src/reasoncodes";
const esc = (s: string) => s.replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);
const rc = JSON.parse(readFileSync("../../docs/dev/reason_codes.json", "utf8"));
rc.plant_unresponsive ??= { zh: "对象无响应", kind: "stop", message_zh: "对象无响应", causes: ["没上电", "接线", "方向（执行器 / 传感器极性接反）", "执行器饱和"] };
rc.resuming ??= { zh: "正在恢复连接", kind: "blocker" };
rc.estop_latched_ident_deferred ??= { zh: "急停中，暂不识别板子", kind: "blocker" };
setReasonCodes(rc);
// 1 resuming：状态栏绝不「已连接」（board=connected 也一样）
for (const board of ["connected", "lost", undefined]) {
  const t = linkTag({ board, reason: "resuming" }, Date.now(), Date.now());
  assert.match(t.text, /正在恢复连接/); assert.doesNotMatch(t.text, /已连接/); assert.equal(t.tone, "busy");
}
assert.equal(linkTag({ board: "connected" }, null, 0).text, "已连接");
assert.match(linkView({ board: "connected", reason: "resuming" }).text, /正在恢复连接/);
assert.equal(linkView({ board: "lost", reason: "resuming", message_zh: "本地服务重启后正在恢复连接" }).text, "本地服务重启后正在恢复连接", "message_zh 优先");
// 2 闸门：resuming / 身份未定 / 急停暂不识别 都锁执行器
assert.equal(actGateOf({ link: { board: "connected", reason: "resuming" } })!.code, "resuming");
const pend = boardIdOf({ board_uid: null, uid_supported: null, board_ident_source: "pending" })!;
assert.equal(actGateOf({ link: { board: "connected" }, pending: !!pend.pending })!.text, "正在识别板子…");
const err = { code: "estop_latched_ident_deferred", message: "急停中，暂不识别板子", data: { reason: "estop_latched_ident_deferred", message_zh: "急停中，暂不识别板子" } };
const d = deferredOf(err)!; assert.equal(d.text, "急停中，暂不识别板子");
assert.equal(actGateOf({ link: { board: "connected" }, deferred: d })!.code, "estop_latched_ident_deferred");
assert.ok(fromBlockersGate([{ blocker_code: "estop_latched_ident_deferred" }]));
assert.equal(actGateOf({ link: { board: "connected" } }), null);
assert.ok(isGateCode(codeOf({ code: "resuming" }))); assert.ok(!isGateCode(codeOf({ code: "timeout" })));
assert.match(gateBannerHtml(d, esc), /data-gate="estop_latched_ident_deferred"/);
// 3 通用：未知新原因码按原因表 / message_zh 出字
setReasonCodes({ ...rc, brand_new_code: { zh: "新的阻塞原因", kind: "blocker" } });
assert.equal(reasonText("brand_new_code"), "新的阻塞原因");
assert.equal(reasonText("brand_new_code", { message_zh: "后端原文" }), "后端原文");
setReasonCodes(rc);
// 4 默认阶跃时长提示 + 跳声明
const r = { reason: "plant_unresponsive", best: null, dur_cap_notice_zh: "未声明阶跃时长上限，使用默认 12 s", fix_action: "edit_declaration", fix_field: "link.step.max_step_dur_ms" };
const n = durCapNoteHtml(r, esc); assert.match(n, /使用默认 12 s/); assert.match(n, /data-decl-unit="link\.step\.max_step_dur_ms"/);
assert.equal(durCapNoteHtml({ reason: "plant_unresponsive" }, esc), "");
const card = resultCardHtml(r as any as Stopped, esc, { canApply: true, applyReady: true } as any);
assert.match(card, /rc-durcap/); assert.match(card, /对象无响应/); assert.match(card, /没上电/);
// 5 接线：main 的 error / toast / blockers / showLink 都喂闸门
const main = readFileSync("src/main.ts", "utf8");
assert.match(main, /gate\.blk = fromBlockersGate/); assert.match(main, /deferredOf\(e\)/); assert.match(main, /runState\.onLink\(m\.board\); renderFwSafe\(\)/);
console.log("r10x ok");
