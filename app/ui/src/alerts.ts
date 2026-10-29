// 底部告警条：严重事件（急停 / 看门狗 / CRC 突增，来自事件时间线）一直挂着，直到人点“知道了”。
// 判级只看事件 kind，不认对象；toast 几秒就没了，比赛现场一回头就错过——这里不会。
import { Ev } from "./timeline";
export const SERIOUS = new Set(["estop", "watchdog", "crc"]);
export class Alerts {
  list: Ev[] = [];
  private acked = -1;                       // 已确认到的事件序号（含）
  offer(e: Ev): boolean { if (!SERIOUS.has(e.kind) || e.i <= this.acked || this.list.some(x => x.i === e.i)) return false; this.list.push(e); return true; }
  top() { return this.list.length ? Math.max(...this.list.map(e => e.i)) : -1; }
  ack(upto = this.top()) { this.acked = Math.max(this.acked, upto); this.list = this.list.filter(e => e.i > this.acked); }
  reset() { this.list = []; this.acked = -1; }
}
