import { mergeEv, kindOf, Ev } from "../src/timeline.ts";
const e = (i: number): Ev => ({ i, kind: "param", text: "kp = " + i, log_t: i, plot_t: i });
const m = mergeEv([e(0), e(2)], [e(2), e(1), e(3)], 3);
if (m.map(x => x.i).join() !== "1,2,3") throw "mergeEv " + JSON.stringify(m);
if (kindOf("estop")[1] !== "--crit" || kindOf("nope")[0] !== "nope") throw "kindOf";
console.log("timeline ok");
