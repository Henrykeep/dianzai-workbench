import { stripLegacy, evText, evColor, bannerHint, clearedLine, CLEARED_SP, EstopSpans, RestoreTarget } from "../src/estophist.ts";
const ok = (c: boolean, m: string) => { if (!c) throw m; };
// 1 时间线文案
ok(evText({ kind: "estop", cause_zh: "界面急停按钮", message_zh: "x R" }) === "界面急停按钮", "cause_zh 优先");
ok(evText({ kind: "estop", message_zh: '界面急停按钮触发，确认安全后点"解除急停"R' }) === "界面急停按钮触发", "旧文案去提示 " + evText({ kind: "estop", message_zh: '界面急停按钮触发，确认安全后点"解除急停"R' }));
ok(evText({ kind: "estop", text: "急停，板子已锁存 → 确认安全后点“解除急停 R”" }) === "急停，板子已锁存", "r41b 实测旧文案");
ok(stripLegacy("心跳超时 R") === "心跳超时", "去末尾 R");
ok(stripLegacy("解除急停R") === "解除急停", "去粘连 R");
ok(stripLegacy("ROBOT") === "ROBOT", "不误伤");
ok(evText({ kind: "param", text: "kp R" }) === "kp R", "非急停不动");
ok(evColor("estop", "--crit", false) === "--muted" && evColor("estop", "--crit", true) === "--crit" && evColor("param", "--acc-t", false) === "--acc-t", "历史中性");
ok(bannerHint(true, { kind: "estop", fix_hint_zh: "确认安全后点解除急停" }) === "确认安全后点解除急停" && bannerHint(false, { kind: "estop", fix_hint_zh: "x" }) === "", "fix_hint 只在锁存");
// 4 灰色记录
const L = clearedLine(Date.UTC(2026, 0, 1, 1, 2, 3), "界面急停");
ok(/^\d\d:\d\d:\d\d 急停已解除 · 设定值已清零，需重新下发目标（之前：界面急停）$/.test(L), "clearedLine " + L);
ok(!clearedLine(0, null).includes("之前") && clearedLine(0).includes(CLEARED_SP), "无 cause");
// 3 曲线竖线
const s = new EstopSpans(); s.latch(1); s.latch(1.5); s.clear(3);
ok(s.list.length === 1 && s.list[0].a === 1 && s.list[0].b === 3, "span");
ok(s.marks().map(m => m.tag + m.color).join() === "急停--crit,解除--muted", "marks");
s.latch(5); ok(s.marks().length === 3 && s.list[1].b == null, "锁存中");
// 5 恢复按钮：本地服务字段优先
const r = new RestoreTarget(); r.noteSent(45); r.onLatch(90); ok(r.value() == null, "锁存中不显示"); r.onClear();
ok(r.value() === 90 && r.label("deg") === "恢复急停前目标 90°", "sp_before_latch 优先 " + r.label("deg"));
ok(r.take() === 90 && r.value() == null, "点击后收起");
// 字段缺失：用界面最后值
const r2 = new RestoreTarget(); r2.noteSent(45); r2.onLatch(undefined); r2.onClear(); ok(r2.value() === 45, "兜底");
// status 补报覆盖兜底
const r3 = new RestoreTarget(); r3.noteSent(45); r3.onLatch(null); r3.onReport(90); r3.onClear(); ok(r3.value() === 90, "补报");
// 用户改目标 / 再次急停即消失；从不自动
r2.onEdit(); ok(r2.value() == null, "编辑后消失");
const r4 = new RestoreTarget(); r4.noteSent(30); r4.onLatch(); r4.onClear(); r4.onLatch(); ok(r4.value() == null, "再次锁存消失");
const r5 = new RestoreTarget(); r5.onLatch(); r5.onClear(); ok(r5.value() == null && r5.label() === "", "没值不显示");
console.log("estophist ok");
