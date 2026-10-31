// 与侧车的 WebSocket：自动重连；rpc() 返回 Promise；推送消息交给 on()
export type Msg = { type: string; [k: string]: any };
export type Err = { code: string; message: string; fix?: string };

export class Link {
  private ws?: WebSocket;
  private rid = 0;
  private wait = new Map<number, (m: Msg) => void>();
  private subs: ((m: Msg) => void)[] = [];
  open = false;
  onState: (open: boolean) => void = () => {};

  constructor(private url: string) { this.dial(); }

  private dial() {
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => { this.open = true; this.onState(true); };
    ws.onclose = () => {
      this.open = false; this.onState(false);
      this.wait.forEach(r => r({ type: "reply", ok: false, error: { code: "ws_closed", message: "与本地服务的连接断了", fix: "本地服务会自动重启/重连；仍不行重开程序" } }));
      this.wait.clear();
      setTimeout(() => this.dial(), 800);
    };
    ws.onmessage = e => {
      const m: Msg = JSON.parse(e.data);
      if (m.type === "reply" && this.wait.has(m.rid)) { this.wait.get(m.rid)!(m); this.wait.delete(m.rid); return; }
      this.subs.forEach(f => f(m));
    };
  }

  on(f: (m: Msg) => void) { this.subs.push(f); }

  /** 启动瞬间 / 重连中最多等 3 s 再报“未连接”，免得一打开就弹假错误 */
  private ready(ms = 3000): Promise<boolean> {
    if (this.open) return Promise.resolve(true);
    return new Promise(r => {
      const t0 = Date.now();
      const tick = () => (this.open ? r(true) : Date.now() - t0 > ms ? r(false) : setTimeout(tick, 50));
      tick();
    });
  }

  async rpc<T = any>(op: string, args: Record<string, unknown> = {}): Promise<T> {
    await this.ready();
    return new Promise((res, rej) => {
      if (!this.open || !this.ws) return rej({ code: "ws_closed", message: "本地服务未连接", fix: "稍等自动重连；开发模式下先运行 python -m dzbench" } as Err);
      const rid = ++this.rid;
      this.wait.set(rid, m => (m.ok ? res(m.data) : rej(m.error)));
      this.ws.send(JSON.stringify({ op, rid, ...args }));
    });
  }

  /** 急停专用：不等回复、不排队，连上就立刻发 */
  fire(op: string, args: Record<string, unknown> = {}) { if (this.open) this.ws!.send(JSON.stringify({ ...args, op, rid: ++this.rid })); }
}
