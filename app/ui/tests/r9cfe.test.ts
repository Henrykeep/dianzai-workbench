import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setReasonCodes, reasonCodes } from "../src/reasoncodes";
import { resultCardHtml, type Stopped } from "../src/iterui";
import { conflictOf } from "../src/boardid";
// fix-r9c bd76e21：plant_unresponsive 带 output_stopped；原因表 stops_output → stop；文案不重复
setReasonCodes(readFileSync("../../docs/dev/reason_codes.json", "utf8"));
assert.equal(reasonCodes().plant_unresponsive?.stop, true);
const h = resultCardHtml({ type: "iterate.stopped", reason: "plant_unresponsive", message_zh: "对象无响应", rounds: 0, best: null, output_stopped: true } as any as Stopped, (s: string) => s, { canApply: true, applyReady: true });
assert.match(h, /已停止输出/); assert.ok(!/对象无响应（对象无响应）/.test(h), "message_zh 与原因同文不重复");
assert.ok(!/id="it-write"/.test(h), "无结论不给采用");
// schema_conflict 按种类照用后端 fix_action
for (const k of ["clear_schema_cache", "build", "reflash"]) assert.equal(conflictOf({ code: "schema_conflict", message_zh: "x", fix_action: k })!.fix, k);
console.log("r9cfe ok");
