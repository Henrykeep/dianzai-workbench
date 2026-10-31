"""WebSocket 服务：UI（Tauri 或浏览器）与会话之间的唯一通道。

UI → 侧车：{"op": ..., "rid": 可选请求号, ...}；侧车回 {"type":"reply","rid":..,"ok":..,"data"|"error"}
侧车 → UI：status（4 Hz）/ telem（≈60 Hz，min-max 抽稀）/ schema / param / proposal / error / estop
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import json
import traceback
import os
import pathlib

import websockets

from . import events, lastsession, snapshots
from . import project as project_mod
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
from .export import ExportError, dzlog_to_csv
from .session import LinkError, Session
from .notices import Notifier, cleared_notice

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
        from .progress import Progress
        from . import doctor as _doctor
        self.progress = Progress(self.session, self.svc, lambda: _doctor.run(str(self.svc.gw.root)))
        self.svc.progress_src = self.progress
        self.recovered = lastsession.take_unclean()      # 上次侧车是不是崩了
        # 缺口 #25：Agent（LLM 长调用）独占一个线程，按顺序排队；不占默认线程池，绝不在事件循环里跑。
        # 上位机心跳是 Session 的独立线程（_host_heartbeat），不经过事件循环，也不等 Agent。
        self.agent_pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="dz-agent")
        self.tick_pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="dz-tick")
        self.estop_pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="dz-estop")
        self.agent_queue: list[str] = []          # 等待中的 msg_id（不含正在跑的）
        self.agent_running: str | None = None
        self._msg_ids = itertools.count(1)
        self.notifier = Notifier()

    # 线程安全的广播
    def emit(self, msg: dict) -> None:
        if self.loop:
            if msg.get("type") == "estop" and msg.get("state") == "cleared":
                # 固件确认解除（心跳 bit10 清零）后才有 cleared；固定提醒紧跟其后、同一协程里保序，只一次
                async def _both():
                    await self._broadcast(msg)
                    await self._broadcast(cleared_notice())
                self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_both()))
                return
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast(msg)))

    async def _broadcast(self, msg: dict) -> None:
        ev = events.from_broadcast(msg)
        if ev:
            self.session.mark(*ev)                    # mark 再走 emit → 下一轮广播出 {"type": "event"}
        if not self.clients:
            return
        data = json.dumps(msg, ensure_ascii=False)
        await asyncio.gather(*(c.send(data) for c in list(self.clients)), return_exceptions=True)

    def _tick_collect(self, n: int) -> list[dict]:
        """在 dz-tick 线程里读会话（这些读要拿 session.lock）：别的线程长持锁时只卡这条线程，不卡事件循环/急停。"""
        out = []
        new = self.session.take_new()
        if new:
            t = [s[0] for s in new]
            ys = {k: [float(s[1][k]) for s in new] for k in new[0][1] if k != "t_ms"}
            t, ys = minmax(t, ys, MAX_POINTS)
            out.append({"type": "telem", "t": t, "y": ys})
        if self.session.raw_on:
            raw = self.session.take_raw()
            if raw:
                out.append({"type": "raw", "c": [[round(t, 4), d, b.hex()] for t, d, b in raw]})
        ls = self.session.link_state()
        if ls:
            out.append(ls)
        if n % (UI_HZ // 4) == 0:
            pc = self.progress.changed()            # 进度有变化才推（依赖自检结果缓存，见 progress.py）
            if pc:
                out.append(pc)
                out.extend(self.notifier.update(pc))  # 新增阻塞项：以 Agent 身份主动提醒（模板，不调大模型）
            out.append(self.session.status() | {"clients": len(self.clients)})
        return out

    async def _ticker(self) -> None:
        n = 0
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(1 / UI_HZ)
            n += 1
            for msg in await loop.run_in_executor(self.tick_pool, self._tick_collect, n):
                await self._broadcast(msg)

    def _selftest_try_h(self) -> dict | None:
        """发 'H'（dzctl 0.12.0+）；没连上/发不出去 → None（按旧固件处理）。急停锁存等其他错误照常抛。"""
        try:
            return self.session.run_selftest()
        except LinkError as e:
            if e.code == "not_connected":
                return None
            raise

    def _selftest_result(self, r: dict | None) -> dict:
        s = self.session
        if r and r.get("ok") is not None:              # 'H' 回包：u32 失败掩码（小端）
            st = {"pass": bool(r["ok"]), "failed_items": r.get("failed_items") or [], "mask": r.get("mask")}
            return {"source": "H", "selftest": st, "pass": st["pass"], "failed_items": st["failed_items"], "message_zh": r.get("message_zh")}
        if getattr(s, "h_supported", False):           # 这块板子回过 'H'，这次却没回：超时，不拿旧结果冒充
            raise LinkError("selftest_timeout", "板子在 1.5 s 内没有回自检结果。", "检查连接后重试；仍超时请读黑匣子查看复位原因", "run_selftest")
        st = s.fw_status().get("selftest")             # 旧固件：心跳里的上电自检结果
        hb = getattr(s, "hb_status", None)
        if st is None:
            if hb is None:
                raise LinkError("selftest_unreported", "当前固件没有上报自检结果（固件早于 dzctl 0.10.0，或该应用尚未接入自检上报）。",
                                "将固件更新到包含自检上报的版本并重新烧录；在此之前可读取黑匣子查看复位原因与安全态记录")
            fail = bool(hb & (1 << 11))                 # 心跳状态字 bit11 = 自检失败（没有逐项明细）
            st = {"pass": not fail, "failed_items": [], "from": "hb_bit11"}
        msg = "自检全部通过" if st.get("pass") else "自检没通过：" + ("；".join(i.get("message_zh") or i.get("key") or "" for i in st.get("failed_items") or []) or "心跳报自检失败（旧固件无逐项明细）")
        return {"source": "heartbeat", "selftest": st, "pass": bool(st.get("pass")), "failed_items": st.get("failed_items") or [], "message_zh": msg}

    async def _op(self, m: dict):
        s, op = self.session, m.get("op")
        run = asyncio.get_running_loop().run_in_executor
        if op == "hello":
            return {"ports": list_ports(), "tools": TOOLS, "status": s.status() | {"clients": len(self.clients)},
                    "recovered": self.recovered, "link": s.link.last, "project": project_mod.current(),
                    "schema": s.schema.summary() if s.schema else None, "params": s.params,
                    "snapshots": snapshots.list_all(s.schema.hash) if s.schema else []}
        if op == "project.list":                       # 可打开的项目（只读，读题页空状态用）
            return {"projects": await run(None, project_mod.list_projects, self.svc.gw.root), "current": project_mod.current()}
        if op == "project.migrate":                    # 旧版写在仓库 examples/ 的用户工程 → $DZBENCH_HOME/projects/：只复制不删；先 confirmed=false 出清单给界面确认卡，人确认后 confirmed=true
            from . import paths as paths_mod
            if m.get("confirmed") is not True:
                return {"needs_confirm": True, "plan": await run(None, paths_mod.migrate_plan, self.svc.gw.root), "dest": str(paths_mod.projects_dir())}
            codes = m.get("codes")
            if codes is None:
                codes = [x["code"] for x in await run(None, paths_mod.migrate_plan, self.svc.gw.root)]
            return await run(None, paths_mod.migrate_copy, self.svc.gw.root, [str(c) for c in codes], True)
        if op == "project.open":                       # 打开已有项目 = 设为当前项目（持久化）+ 推 progress.changed
            try:
                p = await run(None, project_mod.open_project, self.svc.gw.root, m.get("code"))
            except project_mod.ProjectError as e:
                raise LinkError(e.code, e.msg, e.fix, e.fix_action) from None
            pc = self.progress.changed()
            if pc:
                await self._broadcast(pc)
            return {"project": p}
        if op == "progress.get":                       # 项目进度（只读；refresh=true 时重跑依赖自检）
            if m.get("refresh") or self.progress.deps is None:
                await run(None, self.progress.refresh_deps)
            return self.progress.snapshot()
        if op == "list_ports":
            return await run(None, list_ports)
        if op == "serial_lines":                       # {"dtr": true/false/null, "rts": ...}；下次打开串口生效
            from . import ports as _p
            _p.LINES.clear()
            if any(m.get(k) is not None for k in ("dtr", "rts")):   # 都是 null = 回到配置文件 serial.dtr/rts
                _p.LINES.update({k: m.get(k) for k in ("dtr", "rts")})
            return {"ok": True, **_p.line_settings()}
        if op == "serial_lines_set":                   # 连着时直接改 DTR/RTS（线控对话框的开关）
            return await run(None, lambda: s.serial_lines_set(m.get("dtr"), m.get("rts")))
        if op == "serial_pulse":                       # 人点“复位 / 进 BOOT”按钮：按序列拨 DTR/RTS
            return await run(None, lambda: s.serial_pulse(str(m.get("name") or "")))
        if op == "serial_modem":                       # 读 CTS/DSR/RI/CD + 当前 DTR/RTS
            return await run(None, s.serial_modem)
        if op == "serial_stall":                       # 卡死检测秒数（0 = 关）
            s.stall_s = max(0.0, float(m.get("s") or 0))
            return {"stall_s": s.stall_s}
        if op == "connect":
            baud = m.get("baud")
            return await run(None, s.connect, m["port"], None if baud in (None, "auto", 0) else int(baud))
        if op == "disconnect":
            return await run(None, s.disconnect)
        if op == "estop":                      # 不排队：专用单线程发（不占默认线程池，串口写阻塞也不卡事件循环）
            r = await asyncio.get_running_loop().run_in_executor(self.estop_pool, lambda: s.estop(str(m.get("src") or "")[:20], hold=True))
            try:
                await self._broadcast(r)
            finally:
                s.release_estop_events()           # 锁存确认（若已到）排在 requested 之后
            return r
        if op == "cmd":
            # 解除急停：只发 'R'，不重发运动/设定值，不恢复调参。cleared + 固定提醒要等固件心跳 bit10 清零（Server.emit 里推）
            return s.cmd(m["c"], m.get("n"))
        if op == "set_cloud_enabled":              # 比赛模式启用云端：只认界面确认卡的 confirmed=true（与 set_run_mode 同一校验）；Agent 无此工具
            return await run(None, agent_llm.set_cloud_enabled, bool(m.get("enabled")), m.get("confirmed") is True)
        if op == "set_run_mode":                   # 切联机/脱机：界面确认卡确认后才带 confirmed=true（板子还要确认字节）
            return await run(None, s.set_run_mode, str(m.get("mode", "")), bool(m.get("confirmed")))
        if op == "save_params":                    # 板子“保存到 flash”按钮：'W' → 等板子回执（停稳才写）
            return await run(None, s.save_params)
        if op == "blackbox":
            return await run(None, s.blackbox)
        if op == "send_data":
            return s.send_data(int(m["id"]), bytes.fromhex(m.get("hex", "")))
        if op == "param_set":
            return await run(None, s.set_param, m["name"], float(m["value"]))
        if op == "param_read_all":
            return await run(None, s.read_all_params)
        if op == "snapshot_save":
            p = s.snapshot_save(m.get("name", ""), m.get("note", ""), m.get("mode", ""))
            return {"path": p, "snapshots": snapshots.list_all(s.schema.hash)}
        if op == "polarity_check":          # 标定向导第 0 步（实现在 pageops，Agent 工具同一函数）
            from . import pageops
            return pageops.polarity_check(s, m)
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
        if op == "params_restore":                 # 唯一的“回到…”参数入口：source = default（固件默认）| snapshot（某个快照）| best（最好一轮）
            src, ramp = m.get("source"), float(m.get("ramp_s", 0) or 0)
            if src == "best":
                if self.svc._guard().best():
                    return {"source": "best", **(await run(None, self.svc.rollback_best))}
                src, m = "snapshot", {**m, "name": self.svc.BEST_SNAPSHOT}   # 侧车重启后护栏没了：用自动存的那份最好一轮
                if not s.schema or not any(x.get("name") == m["name"] for x in snapshots.list_all(s.schema.hash)):
                    raise LinkError("no_best", "还没有稳定的一轮可回（先做阶跃实验）")
            if src not in ("default", "snapshot"):
                raise LinkError("bad_arg", f"params_restore 的 source 只能是 default / snapshot / best，收到 {src!r}")
            r = await run(None, lambda: s.snapshot_restore(m.get("name") if src == "snapshot" else None, src == "default", ramp))
            return {"source": src, "name": m.get("name"), "written": r}
        if op == "precontest" or op == "precontest_export":
            from . import doctor, precontest
            repo = m.get("repo") or str(self.svc.gw.root)
            r = await run(None, lambda: precontest.run(s, repo, doctor.run(repo), bool(m.get("strict"))))
            if op == "precontest_export":
                r["path"] = await run(None, lambda: precontest.export(r, s, repo, snapshots.base_dir()))
            return r
        if op in ("flow_preview", "flow_accept", "project_chain", "project_apply") and m.get("code"):
            project_mod.set_current(self.svc.gw.root, str(m["code"]))   # 新建 / 打开项目 = 记为当前项目（重启后恢复）
        if op == "fetch_deps":                         # 一键安装缺失依赖（只按自检 fail 项，命令固定，见 deps.py）
            from . import deps
            repo = str(self.svc.gw.root)
            if self.progress.deps is None:
                await run(None, self.progress.refresh_deps)
            r = await run(None, lambda: deps.fetch(self.progress.deps or [], repo))
            await run(None, self.progress.refresh_deps)
            return r
        if op == "run_selftest":                       # 唯一一份：新固件发 'H' 重跑自检；旧固件读心跳上电自检结果；完成后刷新进度
            if not s.status().get("alive"):
                raise LinkError("no_board", "未连接板子，无法执行板上自检。", "先连接板子（或仿真板），再执行自检", "connect")
            try:
                return await run(None, self._selftest_result, await run(None, self._selftest_try_h))
            finally:
                pc = self.progress.changed()
                if pc:
                    await self._broadcast(pc)
        if op == "flow_preview" or op == "flow_accept":     # 项目页引导流程：先暂存区预览，确认才写（dzbench/projflow.py）
            from .projflow import Flow, FlowError
            fl = Flow(self.svc.gw.root)
            try:
                return await run(None, (fl.preview if op == "flow_preview" else fl.accept), m["step"], m)
            except FlowError as e:
                raise LinkError(e.code, e.msg, e.fix, e.fix_action) from None
        if op == "quick_start":     # 一句话起项目：{"op":"quick_start","text":"两轮车速度环，STM32F1"} → 一张确认卡；确认走 agent_action_decide
            from .projflow import FlowError
            try:
                return await run(None, self.svc.quick_start, m["text"])
            except (FlowError, GatewayError) as e:
                raise LinkError(e.code, getattr(e, "msg", None) or getattr(e, "message", ""), e.fix, getattr(e, "fix_action", None)) from None
        if op == "project_chain" or op == "project_apply":   # 项目页“一键走完 ①–⑤（+Keil 注入）”：先整链预览，再一次写入（同 Agent 那张总卡）
            from .projflow import FlowError
            try:
                if op == "project_chain":
                    return await run(None, lambda: self.svc.project_chain(m["code"], **{k: m[k] for k in ("src", "project", "name", "mcu", "tpl", "uvprojx", "app", "hand_edit") if m.get(k)}))
                return await run(None, self.svc.project_apply, m["code"])
            except (FlowError, GatewayError) as e:
                raise LinkError(e.code, e.msg, e.fix, getattr(e, "fix_action", None)) from None
        if op == "score_items" or op == "score_save" or op == "score_writeback":       # 评分页：评分项来自 requirements.yaml；证据按 docs/verify 规范存（dzbench/scoring.py）
            from . import scoring
            try:
                return await run(None, {"score_items": scoring.items, "score_save": scoring.save, "score_writeback": scoring.writeback}[op], self.svc, m)
            except scoring.ScoreError as e:
                raise LinkError(e.code, e.msg, e.fix) from None
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
        if op == "propose":                        # 唯一的提议入口：分析阶跃 / 仿真搜索 / 外部脚本；内置 Agent 的 propose_param_change 落同一种提议卡
            ch = m.get("changes") or {m["name"]: m["value"]}
            return self.svc.propose_hint(ch, m.get("reason", ""), bool(m.get("verify_step")), m.get("source"))
        if op == "proposal_decide":
            r = await run(None, self.agent.decide, int(m["id"]), bool(m["accept"]))
            if self.svc.verify_after_decide(int(m["id"]), r):   # 仿真搜索候选整组已采纳 → 自动验证阶跃（结果走 tune_round）
                async def _verify():
                    try:
                        await run(None, self.svc.run_step_test)
                    except Exception as e:  # noqa: BLE001  错误卡（中文原因），不影响已采纳的参数
                        self.emit(LinkError("verify_step_failed", f"验证阶跃没做成：{e}", "检查 dzbench.json 的 step_test，或手动点“阶跃实验”").as_dict())
                asyncio.ensure_future(_verify())
                r = r | {"verify_step": True}
            return r
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
        if op == "fft" or op == "wave_measure":    # 联调页（实现在 pageops，Agent 工具同一函数）
            from . import pageops
            return await run(None, getattr(pageops, op), self.session, m)
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
        if op == "framedef_set":                    # {"def": {...} | null}：自定义 HEX/文本帧结构（VOFA JustFloat/FireWater 预设）
            return self.session.set_framedef(m.get("def"))
        if op == "framedef_status":
            p = self.session.kv
            return {"framedef": getattr(p, "d", None), "bad": getattr(p, "bad", 0), "fields": list(p.names)}
        if op == "auto_reconnect":
            self.session.auto_reconnect = bool(m.get("on", True))
            return {"on": self.session.auto_reconnect}
        if op == "log_import":                     # 导入 CSV / VOFA 文本 → .dzlog（之后照常回放）
            from .logio import ImportError_, import_to_dzlog
            try:
                return await run(None, lambda: import_to_dzlog(m["path"], self.session.log_dir, float(m.get("period_ms") or 10)))
            except (ImportError_, OSError) as e:
                raise LinkError("import", getattr(e, "message", str(e)), getattr(e, "fix", "")) from e
        if op == "log_export":
            try:
                return await run(None, lambda: dzlog_to_csv(m["path"], fmt=m.get("fmt", "excel")))
            except ExportError as e:
                raise LinkError("export", e.message, e.fix) from e
        # ---- 内置 Agent（docs/18）
        if op == "tune_analyze":
            return await run(None, lambda: self.svc.step_analysis(m.get("y"), m.get("sp"), float(m.get("seconds", 5)),
                                                                   m.get("kp"), m.get("ki"), m.get("kd")))
        if op == "tune_search":                    # 开环阶跃 → 辨识 → 仿真 PSO/分阶段 → top-k（不写板子）
            return await run(None, lambda: self.svc.sim_search(m["y"], m["u"], float(m.get("seconds", 5)), m.get("strategy", "pso"),
                                                               bool(m.get("wide")), int(m.get("top_k", 3))))
        if op == "agent_ask":                      # 正常走 handler 里的 _agent_submit（立即回执 + 排队）；这里只给内部直调
            return await asyncio.get_running_loop().run_in_executor(self.agent_pool, self.svc.ask, m["text"])
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
        if op in ("coproc_get", "coproc_set", "coproc_push", "coproc_start", "coproc_stop", "coproc_status", "coproc_log"):
            from . import deploy                   # 协处理器 SSH 部署对话框（缺口 12）
            if op == "coproc_get":
                return {"cfg": deploy.load(), "presets": deploy.PRESETS}
            if op == "coproc_set":
                return await run(None, lambda: deploy.save(m.get("values") or {}))
            d = deploy.Deployer()
            if op == "coproc_push":
                return await run(None, lambda: d.push(str(m.get("path") or "")))
            if op == "coproc_log":
                return await run(None, lambda: d.log(int(m.get("lines") or 100)))
            if op == "coproc_start":
                return await run(None, d.start)
            if op == "coproc_stop":
                return await run(None, d.stop)
            if op == "coproc_status":
                return await run(None, d.status)
        if op == "probe_config_get":               # 调试探针设置对话框：当前后端 / 探针类型 / 序列号 + 按后端列探针
            return await run(None, lambda: self.svc.probe_config_get(bool(m.get("list", True))))
        if op == "probe_config_set":               # 人在对话框点“保存”：写本机 machine.json
            return await run(None, lambda: self.svc.probe_config_set(m.get("values") or {}))
        if op == "pretune_get":                    # 调参前问答：问题 + 当前偏好
            return self.svc.pretune_get()
        if op == "pretune_set":                    # 人在对话框点“确认”
            return self.svc.pretune_set(m.get("answers"))
        if op == "tune_best":                      # 只读：最好一轮（给“回到最好一轮”按钮的确认框）
            b = self.svc._guard().best()
            return {"round": b.n, "gains": b.gains, "score": round(b.score, 4)} if b else None
        if op == "tune_reset":
            return self.svc.reset_guard()
        if op == "tune_rule_round":                # 无 LLM 模式：规则给一项建议（仍是待确认提议）
            return self.svc.rule_round()
        if op == "tune_sweep_test":                # 同上：用户点 = 已确认；要几十秒，放线程池
            return await run(None, self.svc.run_sweep_test)
        if op == "tune_relay":                     # 调参 → 更多实验 → 无初值一键起步；用户点 = 已确认；十几秒，放线程池
            return await run(None, self.svc.run_relay_tune)
        if op == "tune_step_test":                 # 用户自己点 = 已是人工确认；要几秒，放线程池（以前在事件循环里跑，会卡住广播）
            return await run(None, self.svc.run_step_test)
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
        if op == "agent_models":
            r = await run(None, lambda: agent_llm.discover_models(m.get("form") or {}))
            if r.get("reason") == "contest_mode":      # 比赛模式拦下外部请求：同时推 agent_error，界面统一提示
                await self._broadcast({"type": "agent_error", "code": "contest_mode", "message_zh": r["message_zh"],
                                       "fix_action": r["fix_action"], "human_only": True, "goto": r["goto"], "retryable": False})
            return r
        if op == "agent_ollama":
            return agent_llm.ollama(m.get("action", "check"), m.get("model", ""))
        if op == "agent_config_test":
            return agent_llm.test_connection(m.get("form") or {})
        if op == "agent_config":
            return self.svc.configure(m["set"]) if m.get("set") else agent_llm.public_config() | {"repo": str(self.svc.gw.root)}
        if op == "yaml_writeback":
            return await run(None, lambda: self.svc.yaml_writeback(m.get("path"), m.get("values")))
        if op == "change_decide":
            return await run(None, self.svc.gw.decide, int(m["id"]), bool(m["accept"]))
        if op == "rollback":
            return await run(None, self.svc.gw.rollback, m["commit"])
        raise LinkError("bad_op", f"未知操作 {op}")

    def _queue_state(self) -> dict:
        return {"type": "agent_queue", "running": self.agent_running, "queued": list(self.agent_queue)}

    async def _agent_submit(self, ws, m: dict) -> None:
        """每条用户消息立刻回 agent_ack {msg_id, state}：queued / running / blocked。
        急停锁存时明确拒绝（不排队、不静默丢弃）：ack state=blocked + reply ok=false code=estop_locked，
        消息原文在 ack.text 里交还给界面，解除急停后由用户重发。"""
        rid = m.get("rid")
        mid = str(m.get("msg_id") or f"m{next(self._msg_ids)}")
        s = self.session
        if s.tx_locked:
            cause = (s.estop_cause or {}).get("message_zh") or ""
            msg = "已急停，请先解除" + (f"：{cause}" if cause else "")
            ack = {"type": "agent_ack", "msg_id": mid, "rid": rid, "state": "blocked", "reason": "estop",
                   "source": s.estop_source, "message": msg, "fix_action": "estop_clear", "human_only": True,
                   "text": m.get("text")}
            await self._send(ws, ack)
            await self._send(ws, {"type": "reply", "rid": rid, "op": "agent_ask", "ok": False, "msg_id": mid,
                                  "error": {"type": "error", "code": "estop_locked", "message": msg,
                                            "fix": "确认安全后在界面点“解除急停”，再重发这条消息", "fix_action": "estop_clear"}})
            return
        state = "queued" if (self.agent_running or self.agent_queue) else "running"
        self.agent_queue.append(mid)
        await self._send(ws, {"type": "agent_ack", "msg_id": mid, "rid": rid, "state": state,
                              "position": len(self.agent_queue) - (0 if self.agent_running else 1)})
        await self._broadcast(self._queue_state())
        loop = asyncio.get_running_loop()

        def job():
            self.agent_queue.remove(mid)
            self.agent_running = mid
            self.emit({"type": "agent_ack", "msg_id": mid, "rid": rid, "state": "running", "position": 0})
            self.emit(self._queue_state())
            try:
                return self.svc.ask(m["text"])
            finally:
                self.agent_running = None
                self.emit(self._queue_state())

        async def finish():
            try:
                data = await loop.run_in_executor(self.agent_pool, job)
                rep = {"type": "reply", "rid": rid, "op": "agent_ask", "ok": True, "msg_id": mid, "data": data}
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                rep = {"type": "reply", "rid": rid, "op": "agent_ask", "ok": False, "msg_id": mid,
                       "error": {"type": "error", "code": "internal", "message": f"{type(e).__name__}: {e}",
                                 "fix": "请把这条信息和日志文件发给维护者"}}
            await self._send(ws, rep)
        asyncio.ensure_future(finish())

    @staticmethod
    async def _send(ws, msg: dict) -> None:
        try:
            await ws.send(json.dumps(msg, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001  连接已关
            pass

    async def handler(self, ws) -> None:
        self.clients.add(ws)
        try:
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if m.get("op") == "agent_ask":       # 不 await：Agent 长调用期间同一连接上的急停/其他操作照常处理
                    await self._agent_submit(ws, m)
                    continue
                if m.get("op") == "estop":           # 安全 P0：急停最高优先级，不排在本连接任何操作（烧录/调参/实验）后面
                    await self._reply(ws, m)
                    continue
                # 其他操作按收到的顺序串行执行，但放进后台任务：读消息的循环不被长操作卡住（急停随时能进来）
                prev = getattr(ws, "_dz_chain", None)
                ws._dz_chain = asyncio.ensure_future(self._chained(prev, ws, m))
        finally:
            self.clients.discard(ws)

    async def _chained(self, prev, ws, m: dict) -> None:
        if prev is not None:
            try:
                await prev
            except Exception:  # noqa: BLE001
                pass
        await self._reply(ws, m)

    async def _reply(self, ws, m: dict) -> None:
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
        await self._send(ws, rep)

    async def serve(self, host: str, port: int, ui_dir: pathlib.Path | None = None) -> None:
        self.loop = asyncio.get_running_loop()
        asyncio.get_running_loop().run_in_executor(None, self.progress.refresh_deps)
        ticker = asyncio.ensure_future(self._ticker())
        if self.recovered and self.session.auto_reconnect:            # 上次崩了：自动连回那块板
            rec = dict(self.recovered)
            self.session.resuming = True                                # 第一条 link.state 就是 lost/resuming
            asyncio.get_running_loop().run_in_executor(None, self.session.resume, rec)
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
