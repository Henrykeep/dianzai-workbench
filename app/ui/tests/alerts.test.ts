import { Alerts } from "../src/alerts.ts";
const e = (i: number, kind: string) => ({ i, kind, text: kind, log_t: i, plot_t: i });
const a = new Alerts();
if (a.offer(e(0, "param")) || !a.offer(e(1, "estop")) || a.offer(e(1, "estop")) || !a.offer(e(2, "watchdog"))) throw "offer";
a.ack();
if (a.list.length || a.offer(e(2, "watchdog")) || !a.offer(e(3, "crc"))) throw "ack";   // 已确认的（刷新补历史时）不再弹
console.log("alerts ok");
