// 连接状态唯一来源（前端 store）。横幅、状态栏、连接胶囊都只读这里。
// 现状：sidecar 字段来自 WebSocket 开合，board 字段来自侧车推送的 status；侧车断开时 board 一并置为未连接，
// 避免出现“侧车无响应”横幅与“已连接”同时显示。后端提供统一的连接状态推送后，只改 set() 的调用方。
export type Conn = { sidecar: boolean; board: boolean; alive: boolean };
let cur: Conn = { sidecar: false, board: false, alive: false };
const subs: ((c: Conn) => void)[] = [];
export const conn = {
  get: () => cur,
  set(p: Partial<Conn>) {
    cur = { ...cur, ...p };
    if (!cur.sidecar) cur = { ...cur, board: false, alive: false };
    subs.forEach(f => f(cur));
  },
  on(f: (c: Conn) => void) { subs.push(f); f(cur); },
};
