import { protectRows, UndoLog } from "../src/protect.ts";
const P = (name: string, protect?: string) => ({ name, type: "f32", min: 0, max: 1, default: 0, protect });
const r = protectRows([P("kp"), P("max_rps", "限幅"), P("to", "断线停车"), P("acc", "限幅")], [{ name: "看门狗", value: 500, unit: "ms" }]);
if (r.map(x => x.p?.name ?? x.cat).join() !== "to,max_rps,acc,看门狗" && r.map(x => x.p?.name ?? x.cat).join() !== "max_rps,acc,to,看门狗") throw "rows " + JSON.stringify(r);
if (r.length !== 4 || r[3].fixed?.value !== 500 || r.some(x => x.p?.name === "kp")) throw "rows content";
const u = new UndoLog(2); u.push("a", 1); u.push("a", 2); u.push("a", 3); u.push("b", undefined);
if (u.peek("a") !== 3 || u.pop("a") !== 3 || u.pop("a") !== 2 || u.pop("a") !== undefined || u.peek("b") !== undefined) throw "undo";
console.log("protect ok");
