import { probeOpen, openProject, topLabel, isMissingOp, NO_API } from "../src/project.ts";
const missing = async () => { throw { code: "bad_op", message: "未知操作 project.list" }; };
(async () => {
  if (topLabel({ path: "/x/examples/2026H_ball", name: "2026H 小球" }) !== "2026H 小球") throw "项目名";
  if (topLabel({ path: "/x/examples/foo/", name: "" }) !== "foo" || topLabel(null) !== "") throw "无名回退到目录名 / null 不显示";
  if (!isMissingOp({ code: "bad_op", message: "未知操作 project.open" }) || isMissingOp({ code: "io", message: "磁盘满" })) throw "isMissingOp";
  // 接口不存在 → 不可用 + 原因
  const r0 = await probeOpen(missing); if (r0.ok || r0.note !== NO_API) throw "接口不存在";
  // mock 正常返回
  const calls: any[] = [];
  const rpc = async (op: string, a?: any) => { calls.push([op, a]);
    if (op === "project.list") return [{ code: "p1", name: "小车", updated_at: "2026-10-30 21:00" }];
    if (op === "project.open") return { project: { path: "/w/p1", name: "小车" } }; };
  const r1 = await probeOpen(rpc); if (!r1.ok || r1.items?.[0].code !== "p1") throw "list";
  const o = await openProject(rpc, "p1"); if (!o.ok || o.project?.name !== "小车") throw "open";
  if (JSON.stringify(calls[1]) !== JSON.stringify(["project.open", { code: "p1" }])) throw "open 参数";
  const o2 = await openProject(async () => { throw { code: "bad_op", message: "未知操作 project.open" }; }, "p1");
  if (o2.ok || !o2.note!.includes("未就绪")) throw "open 不存在";
  const r2 = await probeOpen(async () => { throw { code: "io", message: "磁盘满" }; }); if (!r2.ok || !r2.note!.includes("磁盘满")) throw "其它错误照实写、按钮不置灰";
  console.log("project ok");
})().catch(e => { console.error(e); process.exit(1); });
