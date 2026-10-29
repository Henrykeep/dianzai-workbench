import { level, median, merge, Cell } from "../src/hbstrip.ts";
const c = (i: number, fps: number, crc = 0, drops = 0): Cell => ({ i, dt: 1, fps, crc, drops, bytes: 0, log_t: i, plot_t: i });
if (level(c(0, 0), 50) !== "off" || level(c(0, 50, 1), 50) !== "bad" || level(c(0, 50, 0, 2), 50) !== "bad") throw "level bad/off";
if (level(c(0, 20), 50) !== "warn" || level(c(0, 40), 50) !== "ok" || level(c(0, 5), 0) !== "ok") throw "level warn";
if (median([3, 1, 2]) !== 2 || median([1, 2, 3, 4]) !== 2.5 || median([]) !== 0) throw "median";
const m = merge([c(0, 1), c(1, 1)], [c(1, 9), c(2, 1), c(3, 1)], 3);
if (m.length !== 3 || m[0].i !== 1 || m[0].fps !== 1 || m[2].i !== 3) throw "merge " + JSON.stringify(m);
console.log("hbstrip ok");
