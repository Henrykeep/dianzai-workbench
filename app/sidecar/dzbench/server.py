"""WebSocket 服务：UI（Tauri 或浏览器）与会话之间的唯一通道。

UI → 侧车：{"op": ..., "rid": 可选请求号, ...}；侧车回 {"type":"reply","rid":..,"ok":..,"data"|"error"}
侧车 → UI：status（4 Hz）/ telem（≈60 Hz，min-max 抽稀）/ schema / param / proposal / error / estop
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib

import websockets

from . import snapshots
from .agent import llm as agent_llm
from .agent.gateway import GatewayError
from .agent.service import AgentService
from .agent_api import TOOLS, AgentTools
from .downsample import minmax
from .logfile import read_log
from .ports import list_ports
from .sender import Sender
from .spectrum import spectrum
from .export import ExportError, dzlog_to_csv
from .session import LinkError, Session

UI_HZ = 60
MAX_POINTS = 200


class Server:
    def __init__(self):
        self.clients: set = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.session = Session(emit=self.emit)
        self.agent = AgentTools(self.session, self.emit)
        self.svc = AgentService(self.session, self.agent, self.emit)
        self.sender = Sender(self.session, self.emit)

    # 线程安全的广播
    def emit(self, msg: dict) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast(msg)))

    async def _broadcast(self, msg: dict) -> None:
        if not self.clients:
            return
        data = json.dumps(msg, ensure_ascii=False)
        await asyncio.gather(*(c.send(data) for c in list(self.clients)), return_exceptions=True)

    async def _ticker(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(1 / UI_HZ)
            new = self.session.take_new()
            if new:
                t = [s[0] for s in new]
                ys = {k: [float(s[1][k]) for s in new] for k in new[0][1] if k != "t_ms"}
                t, ys = minmax(t, ys, MAX_POINTS)
                await self._broadcast({"type": "telem", "t": t, "y": ys})
            if self.session.raw_on:
                raw = self.session.take_raw()
                if raw:
                    await self._broadcast({"type": "raw", "c": [[round(t, 4), d, b.hex()] for t, d, b in raw]})
            n += 1
            if n % (UI_HZ // 4) == 0:
                await self._broadcast(self.session.status())

    async def _op(self, m: dict):
        s, op = self.session, m.get("op")
        run = asyncio.get_running_loop().run_in_executor
        if op == "hello":
            return {"ports": list_ports(), "tools": TOOLS, "status": s.status(),
                    "schema": s.schema.summary() if s.schema else None, "params": s.params,
                    "snapshots": snapshots.list_all(s.schema.hash) if s.schema else []}
        if op == "list_ports":
            return await run(None, list_ports)
        if op == "connect":
            baud = m.get("baud")
            return await run(None, s.connect, m["port"], None if baud in (None, "auto", 0) else int(baud))
        if op == "disconnect":
            return await run(None, s.disconnect)
        if op == "estop":                      # 不排队，直接在事件循环里发
            r = s.estop()
            await self._broadcast(r)
            return r
        if op == "cmd":
            return s.cmd(m["c"], m.get("n"))
        if op == "send_data":
            return s.send_data(int(m["id"]), bytes.fromhex(m.get("hex", "")))
        if op == "param_set":
            return await run(None, s.set_param, m["name"], float(m["value"]))
        if op == "param_read_all":
            return await run(None, s.read_all_params)
        if op == "snapshot_save":
            p = s.snapshot_save(m.get("name", ""), m.get("note", ""))
            return {"path": p, "snapshots": snapshots.list_all(s.schema.hash)}
        if op == "snapshot_list":
            return snapshots.list_all(s.schema.hash) if s.schema else []
        if op == "snapshot_restore":
            return await run(None, lambda: s.snapshot_restore(m.get("name"), bool(m.get("defaults"))))
        if op == "log_list":
            d = s.log_dir
            return [{"path": str(f), "size": f.stat().st_size, "header": read_log(f)[0]}
                    for f in sorted(d.glob("*.dzlog"), reverse=True)[:30]] if d.is_dir() else []
        if op == "replay":
            return await run(None, lambda: s.connect("replay:" + m["path"], log=False))
        if op == "propose":
            return self.agent.propose_param_change(m["name"], m["value"], m.get("reason", ""), m.get("source", "user"))
        if op == "proposal_decide":
            return await run(None, self.agent.decide, int(m["id"]), bool(m["accept"]))
        if op == "agent_tool":
            return await run(None, self.agent.call, m["tool"], m.get("args", {}))
        if op == "replay_ctl":
            r = self.session.replay_ctl(m.get("seek"), m.get("speed"), m.get("pause"))
            if m.get("seek") is not None:
                await self._broadcast({"type": "seeked", **r})
            return r
        if op == "fft":
            name = m["field"]
            t, y = self.session.window_field(name, float(m.get("seconds", 30)))
            sch = self.session.schema
            per = (sch.d["telemetry"].get("period_ms") or 0) / 1000 if sch else 0
            return await run(None, lambda: spectrum(t, y, per or None) | {"field": name})
        if op == "send_raw":
            data = bytes.fromhex(m["hex"]) if "hex" in m else m["text"].encode("utf-8")
            return self.session.send_raw(data)
        if op == "preset_list":
            return self.sender.list()
        if op == "preset_save":
            r = self.sender.save_preset(m["preset"])
            self.emit({"type": "sender", "presets": r})
            return r
        if op == "preset_delete":
            r = self.sender.delete_preset(m["name"])
            self.emit({"type": "sender", "presets": r})
            return r
        if op == "preset_send":
            return self.sender.send(m["name"])
        if op == "preset_timer":
            if m.get("on", True):
                self.sender.start_timer(m["name"], int(m["period_ms"]), int(m.get("count", 0)))
            else:
                self.sender.stop_timer(m["name"])
            self.emit({"type": "sender", "presets": self.sender.list()})
            return self.sender.list()
        if op == "preset_trigger":
            if m.get("on", True):
                self.sender.add_trigger(m["name"], m["field"], m["op_"], m["value"], int(m.get("cooldown_ms", 200)))
            else:
                self.sender.remove_trigger(m["name"])
            self.emit({"type": "sender", "presets": self.sender.list()})
            return self.sender.list()
        if op == "raw_monitor":
            self.session.raw_on = bool(m.get("on", True))
            return {"on": self.session.raw_on}
        if op == "auto_reconnect":
            self.session.auto_reconnect = bool(m.get("on", True))
            return {"on": self.session.auto_reconnect}
        if op == "log_export":
            try:
                return await run(None, dzlog_to_csv, m["path"])
            except ExportError as e:
                raise LinkError("export", e.message, e.fix) from e
        # ---- 内置 Agent（docs/18）
        if op == "tune_analyze":
            return await run(None, lambda: self.svc.step_analysis(m.get("y"), m.get("sp"), float(m.get("seconds", 5)),
                                                                   m.get("kp"), m.get("ki"), m.get("kd")))
        if op == "tune_propose":
            return self.svc.propose_hint(m["changes"], m.get("reason", "阶跃分析规则建议"))
        if op == "agent_ask":
            return await run(None, self.svc.ask, m["text"])
        if op == "agent_reset":
            return self.svc.loop.reset()
        if op == "agent_config":
            return self.svc.configure(m["set"]) if m.get("set") else agent_llm.public_config() | {"repo": str(self.svc.gw.root)}
        if op == "yaml_writeback":
            return await run(None, lambda: self.svc.yaml_writeback(m.get("path"), m.get("values")))
        if op == "change_decide":
            return await run(None, self.svc.gw.decide, int(m["id"]), bool(m["accept"]))
        if op == "change_list":
            return {"pending": self.svc.gw.pending(), "history": await run(None, self.svc.gw.history)}
        if op == "rollback":
            return await run(None, self.svc.gw.rollback, m["commit"])
        raise LinkError("bad_op", f"未知操作 {op}")

    async def handler(self, ws) -> None:
        self.clients.add(ws)
        try:
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                rid = m.get("rid")
                try:
                    data = await self._op(m)
                    rep = {"type": "reply", "rid": rid, "op": m.get("op"), "ok": True, "data": data}
                except (LinkError, GatewayError) as e:
                    rep = {"type": "reply", "rid": rid, "op": m.get("op"), "ok": False, "error": e.as_dict()}
                except Exception as e:  # noqa: BLE001
                    rep = {"type": "reply", "rid": rid, "op": m.get("op"), "ok": False,
                           "error": {"type": "error", "code": "internal", "message": f"{type(e).__name__}: {e}",
                                     "fix": "请把这条信息和日志文件发给维护者"}}
                await ws.send(json.dumps(rep, ensure_ascii=False, default=str))
        finally:
            self.clients.discard(ws)

    async def serve(self, host: str, port: int, ui_dir: pathlib.Path | None = None) -> None:
        self.loop = asyncio.get_running_loop()
        asyncio.ensure_future(self._ticker())
        async with websockets.serve(self.handler, host, port, max_size=2**22):
            print(f"dzbench sidecar ws://{host}:{port}", flush=True)
            if ui_dir:
                await _serve_static(host, port + 1, ui_dir)
            await asyncio.Future()


async def _serve_static(host: str, port: int, root: pathlib.Path) -> None:
    """开发/浏览器模式：不装 Tauri 也能用浏览器打开 UI（http://host:port+1）。"""
    import functools
    import http.server
    import threading
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer((host, port), h)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"dzbench ui http://{host}:{port}/", flush=True)
