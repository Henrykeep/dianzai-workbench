import { WIZ } from "../src/calwiz.ts";
const by = (id: string) => WIZ.find(s => s.id === id)!;
if (by("line").outs[0].calc({ "w|0": 3000, "b|0": 400 }) !== 1700) throw "line thr = 黑白中点";
if (by("imu").outs.map(o => o.calc({ "s|0": 0.1, "s|1": -0.2, "s|2": 0.03 })).join() !== "0.1,-0.2,0.03") throw "imu bias = 静止均值";
if (!Number.isNaN(by("line").outs[0].calc({ "w|0": 1 }))) throw "缺一段不出值";
for (const s of WIZ) if (!s.check.length || !s.slots.length) throw "每步都有准备清单和录制段 " + s.id;
console.log("calwiz ok");
