"""WebSocket 服务：UI（Tauri 或浏览器）与会话之间的唯一通道。

UI → 侧车：{"op": ..., "rid": 可选请求号, ...}；侧车回 {"type":"reply","rid":..,"ok":..,"data"|"error"}
侧车 → UI：status（4 Hz）/ telem（≈60 Hz，min-max 抽稀）/ schema / param / proposal / error / estop
"""
from __future__ import annotations

import asyncio
import json
import traceback
import os
import pathlib

import websockets

from . import events, lastsession, snapshots
from .agent import llm as agent_llm
from .agent.gateway import GatewayError
from .agent.guard import GuardError
from .config import ConfigError
from .elfsym import ElfError
from .flash import FlashError
from .agent.service import AgentService
from .agent_api import TOOLS, AgentTools
from .downsample import minmax
from .logfile import read_header
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
        self.recovered = lastsession.take_unclean()      # 上次侧车是不是崩了

    # 线程安全的广播
    def emit(self, msg: dict) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast(msg)))

    async def _broadcast(self, msg: dict) -> None:
        ev = events.from_broadcast(msg)
        if ev:
            self.session.mark(*ev)                    # mark 再走 emit → 下一轮广播出 {"type": "event"}
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
                await self._broadcast(self.session.status() | {"clients": len(self.clients)})

    async def _op(self, m: dict):
        s, op = self.session, m.get("op")
        run = asyncio.get_running_loop().run_in_executor
        if op == "hello":
            return {"ports": list_ports(), "tools": TOOLS, "status": s.status() | {"clients": len(self.clients)},
                    "recovered": self.recovered,
                    "schema": s.schema.summary() if s.schema else None, "params": s.params,
                    "snapshots": snapshots.list_all(s.schema.hash) if s.schema else []}
        if op == "list_ports":
            return await run(None, list_ports)
        if op == "serial_lines":                       # {"dtr": true/false/null, "rts": ...}；下次打开串口生效
            from . import ports as _p
            _p.LINES.clear()
            if any(m.get(k) is not None for k in ("dtr", "rts")):   # 都是 null = 回到配置文件 serial.dtr/rts
                _p.LINES.update({k: m.get(k) for k in ("dtr", "rts")})
            return {"ok": True, **_p.line_settings()}
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
        if op == "blackbox":
            return await run(None, s.blackbox)
        if op == "send_data":
            return s.send_data(int(m["id"]), bytes.fromhex(m.get("hex", "")))
        if op == "param_set":
            return await run(None, s.set_param, m["name"], float(m["value"]))
        if op == "param_read_all":
            return await run(None, s.read_all_params)
        if op == "snapshot_save":
            p = s.snapshot_save(m.get("name", ""), m.get("note", ""))
            return {"path": p, "snapshots": snapshots.list_all(s.schema.hash)}
        if op == "polarity_check":          # 标定向导第 0 步：只读遥测窗口判方向（app/sidecar/dzbench/agent/polarity.py）
            from .agent import polarity
            secs = float(m.get("seconds", 3.0))
            names = [n for n in (m["y"], m.get("e"), m.get("u")) if n]
            win = {n: s.window_field(n, secs) for n in names}
            r = polarity.check_window(win, m["step"], y=m["y"], e=m.get("e"), u=m.get("u"),
                                      pushed_dir=int(m.get("pushed_dir", 1)), u_min=float(m.get("u_min", 0.0)))
            if "signs" in m:                 # 前端把 push/jog 两步的结果攒齐后再要结论
                g = m["signs"]
                r["verdict"] = polarity.verdict(g.get("sensor", 0), g.get("err", 0), g.get("ctrl", 0), g.get("act", 0))
            return r
        if op == "params_readback":
            path = m.get("path")
            if not path:                    # 界面按钮：默认写到 ~/.dzbench/readback/<时间>.txt
                import time as _t
                from . import snapshots as _sn
                d = _sn.base_dir() / "readback"
                d.mkdir(parents=True, exist_ok=True)
                path = str(d / _t.strftime("params-%Y%m%d-%H%M%S.txt"))
            return {"path": await run(None, lambda: s.export_readback(path))}
        if op == "snapshot_list":
            return snapshots.list_all(s.schema.hash) if s.schema else []
        if op == "snapshot_restore":
            return await run(None, lambda: s.snapshot_restore(m.get("name"), bool(m.get("defaults"))))
        if op == "precontest" or op == "precontest_export":
            from . import doctor, precontest
            repo = m.get("repo") or str(self.svc.gw.root)
            r = await run(None, lambda: precontest.run(s, repo, doctor.run(repo), bool(m.get("strict"))))
            if op == "precontest_export":
                r["path"] = await run(None, lambda: precontest.export(r, s, repo, snapshots.base_dir()))
            return r
        if op == "doctor":
            from . import doctor
            # 没指定就查侧车实际在用的工程仓库（DZBENCH_REPO / 配置 repo），以前传 None 会误报“没有 dzbench.json”（docs/29 F12）
            return await run(None, lambda: doctor.run(m.get("repo") or str(self.svc.gw.root)))
        if op == "log_list":
            d = s.log_dir
            return [{"path": str(f), "size": f.stat().st_size, "header": read_header(f),
                     "recording": bool(s.log and str(s.log.path) == str(f))}
                    for f in sorted(d.glob("*.dzlog"), reverse=True)[:30]] if d.is_dir() else []
        if op == "replay":
            return await run(None, lambda: s.connect("replay:" + m["path"], log=False))
        if op == "propose":
            return self.agent.propose_param_change(m["name"], m["value"], m.get("reason", ""), m.get("source", "user"))
        if op == "proposal_decide":
            return await run(None, self.agent.decide, int(m["id"]), bool(m["accept"]))
        if op == "agent_tool":
            return await run(None, self.agent.call, m["tool"], m.get("args", {}))
        if op == "health":
            return s.health.history()
        if op == "timeline":
            return {"events": s.timeline.history(), "acked": s.timeline.acked}
        if op == "alert_ack":
            r = {"type": "alert_ack", "upto": s.timeline.ack(m["upto"])}
            await self._broadcast(r)
            return r
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
                return await run(None, lambda: dzlog_to_csv(m["path"], fmt=m.get("fmt", "excel")))
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
        if op == "agent_undo":                     # 人点“撤销 Agent 上一步”：参数改回 / git revert
            return await run(None, self.svc.undo_last)
        if op == "agent_set_mode":                 # 工作模式：通用 / 诊断 / 调参 / 改代码 / 审查（只收窄工具）
            return self.svc.set_mode(m["mode"])
        if op == "agent_tune_finish":              # 人点“保留 / 恢复原值”（Agent 调过的参数）
            return await run(None, self.svc.tune_finish, bool(m["keep"]))
        if op == "agent_journal":
            return self.svc.journal_list()
        if op == "agent_reset":
            return self.svc.loop.reset()
        if op == "agent_action_decide":            # 风险等级 human 的动作卡：人点“执行/拒绝”（烧录要几秒，放线程池）
            return await run(None, self.svc.action_decide, int(m["id"]), bool(m["accept"]))
        if op == "tune_reset":
            return self.svc.reset_guard()
        if op == "tune_rule_round":                # 无 LLM 模式：规则给一项建议（仍是待确认提议）
            return self.svc.rule_round()
        if op == "tune_sweep_test":                # 同上：用户点 = 已确认；要几十秒，放线程池
            return await run(None, self.svc.run_sweep_test)
        if op == "tune_step_test":                 # 用户自己点 = 已是人工确认
            return self.svc.run_step_test()
        # 编译 / 烧录 / 回滚都走风险网关：界面按钮和 Agent 同一条路（烧录、回滚 = human，弹确认卡；以前这里直接调烧录器，绕过了确认）
        if op == "build":
            return await run(None, lambda: self.svc.gate("build", {}, self.svc.build))
        if op == "flash":
            return await run(None, lambda: self.svc.gate("flash", {}, lambda: self.svc.flasher.flash(True)))
        if op == "flash_rollback":
            return await run(None, lambda: self.svc.gate("flash_rollback", {}, lambda: self.svc.flasher.rollback(True)))
        if op == "elf_symbols":
            return await run(None, lambda: self.svc.elf_symbols(m.get("q", "")))
        if op == "watch_start":
            return await run(None, lambda: self.svc.watch_start(m["vars"], int(m.get("period_ms", 20))))
        if op == "watch_stop":
            return self.svc.watch_stop()
        if op == "agent_config":
            return self.svc.configure(m["set"]) if m.get("set") else agent_llm.public_config() | {"repo": str(self.svc.gw.root)}
        if op == "yaml_writeback":
            return await run(None, lambda: self.svc.yaml_writeback(m.get("path"), m.get("values")))
        if op == "change_decide":
            return await run(None, self.svc.gw.decide, int(m["id"]), bool(m["accept"]))
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
                    ev = events.from_reply(m.get("op"), data)
                    if ev:
                        self.session.mark(*ev)
                    rep = {"type": "reply", "rid": rid, "op": m.get("op"), "ok": True, "data": data}
                except (LinkError, GatewayError) as e:
                    rep = {"type": "reply", "rid": rid, "op": m.get("op"), "ok": False, "error": e.as_dict()}
                except (FlashError, GuardError, ElfError, ConfigError) as e:
                    rep = {"type": "reply", "rid": rid, "op": m.get("op"), "ok": False,
                           "error": {"type": "error", "code": getattr(e, "code", type(e).__name__),
                                     "message": getattr(e, "message", str(e)), "fix": getattr(e, "fix", "")}}
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()          # 侧车日志里留完整堆栈，toast 只给一行
                    rep = {"type": "reply", "rid": rid, "op": m.get("op"), "ok": False,
                           "error": {"type": "error", "code": "internal", "message": f"{type(e).__name__}: {e}",
                                     "fix": "请把这条信息和日志文件发给维护者"}}
                await ws.send(json.dumps(rep, ensure_ascii=False, default=str))
        finally:
            self.clients.discard(ws)

    async def serve(self, host: str, port: int, ui_dir: pathlib.Path | None = None) -> None:
        self.loop = asyncio.get_running_loop()
        ticker = asyncio.ensure_future(self._ticker())
        try:
            async with websockets.serve(self.handler, host, port, max_size=2**22):
                print(f"dzbench sidecar ws://{host}:{port}", flush=True)
                if ui_dir:
                    await _serve_static(host, port + 1, ui_dir)
                await asyncio.Future()
        finally:
            ticker.cancel()


async def _serve_static(host: str, port: int, root: pathlib.Path) -> None:
    """开发/浏览器模式：不装 Tauri 也能用浏览器打开 UI（http://host:port+1）。"""
    import functools
    import http.server
    import threading
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer((host, port), h)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"dzbench ui http://{host}:{port}/", flush=True)
