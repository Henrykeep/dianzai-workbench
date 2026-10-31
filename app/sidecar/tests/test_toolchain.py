"""烧录前置条件 / Keil 日志 / HardFault / ELF 变量 / 分层配置 / 风险分级动作卡（全部离线，假探针）。"""
import os
import json
import pathlib
import shutil
import struct
import subprocess
import time

import pytest

from dzbench import config, elfsym, hardfault, keil
from dzbench.flash import DPIDR, FlashError, Flasher, MockBackend
from dzbench.session import Session

KEIL_LOG = """*** Using Compiler 'V6.19', folder: 'C:\\Keil_v5\\ARM\\ARMCLANG\\Bin'
Build target 'car_2wd'
compiling app_main.c...
../apps/car_2wd/app_main.c(131): warning: #550-D: variable "x" was set but never used
../apps/car_2wd/pid.c:42:5: error: use of undeclared identifier 'kd' [-Wundeclared]
linking...
Program Size: Code=11234 RO-data=566 RW-data=40 ZI-data=2304
"car_2wd\\car_2wd.axf" - 1 Error(s), 1 Warning(s).
"""


def test_keil_log_parse_and_build_runner(tmp_path):
    r = keil.parse_log(KEIL_LOG)
    assert (r["errors"], r["warnings"], r["ok"]) == (1, 1, False)
    assert r["size"]["flash"] == 11234 + 566 + 40 and r["size"]["ram"] == 2344
    d = {x["severity"]: x for x in r["diagnostics"]}
    assert d["error"]["file"].endswith("pid.c") and d["error"]["line"] == 42 and d["warning"]["line"] == 131
    ok = keil.parse_log('Program Size: Code=100 RO-data=0 RW-data=0 ZI-data=0\n"a.axf" - 0 Error(s), 0 Warning(s).')
    assert ok["ok"]
    proj = tmp_path / "p.uvprojx"; proj.write_text("", encoding="utf-8")

    def fake_run(cmd, **kw):
        assert cmd[:2] == ["UV4.exe", "-b"] and "-t" in cmd
        proj.with_suffix(".dzbench_build.log").write_text(KEIL_LOG, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 2, "", "")
    assert keil.build("UV4.exe", str(proj), "car_2wd", runner=fake_run)["ok"] is False


def test_hardfault_core_specific():
    frame = [1, 2, 3, 4, 0, 0x08000123, 0x08000400, 0x01000003]
    m4 = hardfault.decode(frame, 0xFFFFFFFD, "cm4", {"cfsr": (1 << 9) | (1 << 15), "hfsr": 1 << 30, "bfar": 0x40021000})
    names = {c["name"] for c in m4["causes"]}
    assert {"PRECISERR", "FORCED"} <= names and m4["fault_addr"] == "0x40021000" and "PSP" in m4["stack"]
    m0 = hardfault.decode([0x20000001, 0, 0, 0, 0, 0x123, 0x00000400, 0x01000003], 0xFFFFFFF9, "cm0plus", {"cfsr": 1 << 9})
    assert not m0["causes"] and any("没有 CFSR" in n for n in m0["notes"]) and any("非对齐" in n for n in m0["notes"])
    bad = hardfault.decode([0] * 6 + [0, 0], None, "cm3")
    assert {"T_BIT_0", "BAD_PC"} <= {c["name"] for c in bad["causes"]}
    assert hardfault.guess_core("MSPM0G3507") == "cm0plus" and hardfault.guess_core("stm32f407vg") == "cm4"


@pytest.fixture(scope="module")
def elf(tmp_path_factory):
    gcc = shutil.which("arm-none-eabi-gcc")
    if not gcc:
        pytest.skip("没有 arm-none-eabi-gcc")
    d = tmp_path_factory.mktemp("elf")
    (d / "a.c").write_text("float g_speed = 1.5f; volatile int g_count; int twice(int x){return 2*x;}\nvoid _start(void){for(;;) g_count=twice(g_count);}\n", encoding="utf-8")
    subprocess.run([gcc, "-mcpu=cortex-m0plus", "-mthumb", "-O1", "-nostdlib", "-Wl,-Ttext=0x0,-Tdata=0x20200000",
                    "-o", str(d / "a.elf"), str(d / "a.c")], check=True)
    return d / "a.elf"


def test_elf_symbols_and_live_watch(elf, home):
    syms = elfsym.load_symbols(elf)
    assert syms["g_speed"].addr == 0x20200000 and syms["g_speed"].kind == "object"
    assert elfsym.func_at(syms, syms["twice"].addr + 2).startswith("twice+")
    probe = elfsym.MockProbe({0x20200000: bytearray(struct.pack("<f", 1.5) + b"\0" * 12)})
    ev = []
    s = Session(emit=ev.append)
    w = elfsym.SymbolWatch(s, probe, syms)
    info = w.start([{"name": "g_speed", "type": "f32"}], period_ms=5)
    assert info["fields"][0]["addr"] == "0x20200000"
    for k in range(5):
        probe.mem[0x20200000][:4] = struct.pack("<f", 2.0 + k); time.sleep(0.02)
    w.stop()
    vals = [v["g_speed"] for _, v in s.window(10)]
    assert vals and vals[0] >= 1.5 and max(vals) >= 5.0
    assert [e for e in ev if e["type"] == "schema"][0]["schema"]["hash"] == "ELF"
    with pytest.raises(elfsym.ElfError):
        w.resolve([{"name": "nope"}])
    with pytest.raises(elfsym.ElfError):
        elfsym.load_symbols(pathlib.Path(__file__))


def test_layered_config_and_secret_guard(tmp_path, home, monkeypatch):
    (home / "machine.json").write_text(json.dumps({"build": {"keil_uv4": "C:/Keil_v5/UV4/UV4.exe"}, "flash": {"probe": "ABC"}}), encoding="utf-8")
    (tmp_path / "dzbench.json").write_text(json.dumps({"flash": {"target": "mspm0g3507", "probe": "PROJ"}, "core": "cm0plus"}), encoding="utf-8")
    monkeypatch.setenv("DZBENCH_PROBE", "ENV")
    c = config.load(tmp_path)
    assert c["build"]["keil_uv4"].endswith("UV4.exe") and c["flash"]["target"] == "mspm0g3507"
    assert c["flash"]["probe"] == "ENV" and c["flash"]["dry_run"] is True and c["core"] == "cm0plus"
    (tmp_path / "dzbench.json").write_text(json.dumps({"llm": {"api_key": "sk-x"}}), encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


@pytest.fixture
def sim(home):
    if os.name == "nt" or not shutil.which("make") or not shutil.which("cc"):
        pytest.skip("host-sim --stream 需要 POSIX + make + cc")
    s = Session(emit=lambda e: None)
    s.connect("sim:car_2wd", 115200, log=False)
    t0 = time.monotonic()
    while s.schema_hash is None and time.monotonic() - t0 < 5:
        time.sleep(0.05)
    yield s
    s.disconnect()


@pytest.mark.needs_sim
def test_flash_preconditions_dry_run_idcode_backup_verify_rollback(sim, tmp_path, home):
    img = tmp_path / "fw.bin"; img.write_bytes(b"\x01\x02\x03\x04" * 8)
    cfg = config.load(None); cfg["flash"]["target"] = "mspm0g3507"; cfg["flash"]["heartbeat_timeout_s"] = 2
    be = MockBackend(DPIDR["cm0plus"], b"\xaa" * 64)
    f = Flasher(sim, cfg, lambda: be)
    with pytest.raises(FlashError) as e:
        f.flash()
    assert "先编译" in e.value.message and "急停" in e.value.message
    f.note_build(True, str(img), sim.schema_hash)
    sim.estop()
    plan = f.flash()                                     # 默认 dry-run：什么都不做
    assert plan["status"] == "dry_run" and not be.loaded
    img.write_bytes(b"changed")                          # 编译后镜像被改 → 拒绝
    with pytest.raises(FlashError):
        f.flash(dry_run=False)
    img.write_bytes(b"\x01\x02\x03\x04" * 8); f.note_build(True, str(img), sim.schema_hash)
    r = f.flash(dry_run=False)
    assert r["status"] == "flashed" and be.loaded == [str(img)] and be.resets == 1
    assert pathlib.Path(r["backup"]).read_bytes() == b"\xaa" * 32 and r["verify"]["ok"] is True
    f.last_build["schema_hash"] = 0x12345678             # 烧了别的固件 → 心跳哈希不符
    assert f.verify(timeout=0.3)["ok"] is False
    assert f.rollback(dry_run=False)["status"] == "rolled_back" and be.flash[:4] == bytearray(b"\xaa" * 4)
    wrong = Flasher(sim, cfg, lambda: MockBackend(DPIDR["cm4"]))
    wrong.note_build(True, str(img))
    with pytest.raises(FlashError) as e:
        wrong.flash(dry_run=False)
    assert e.value.code == "idcode"


@pytest.mark.needs_sim
def test_service_gate_human_card_and_sim_step_test(sim, tmp_path, home):
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    from dzbench.agent.gateway import GatewayError
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 1.2, "pre_s": 0.4, "y": "spd_a", "sp": "sp_a"}, "flash": {"target": "mspm0g3507"}}), encoding="utf-8")
    ev = []
    svc = AgentService(sim, AgentTools(sim, ev.append), ev.append, root=tmp_path)
    assert svc.sim
    with pytest.raises(GatewayError):
        svc.gate("unlock_rdp", {}, lambda: 1)
    r = svc.gate("flash", {"dry_run": False}, lambda: pytest.fail("human 级工具不能直接执行"))
    assert r["status"] == "pending_human_click"
    card = [e for e in ev if e["type"] == "agent_action"][-1]
    assert card["tool"] == "flash" and "error" in card["preview"]          # 没编译过：预览里就告诉用户前置条件不满足
    assert svc.action_decide(card["id"], False)["status"] == "rejected"
    # 仿真里阶跃实验是 log 级：直接跑，程序给出判定
    out = svc.gate("run_step_test", {}, svc.run_step_test)
    assert out["metrics"]["ok"] and out["verdict"]["action"] in ("continue", "done", "rollback")
    assert (home / "agent_audit.jsonl").read_text(encoding="utf-8").count("run_step_test") == 1
    ctx = svc.tune_context()
    assert ctx["history"] and len(ctx["samples_t_y_sp"]) <= 20 and "每轮只改一个参数" in ctx["rules"]


@pytest.mark.needs_sim
def test_service_four_segment_and_staged_rule_round(sim, tmp_path, home):
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "delta": [0.1, 0], "segments": 4, "hold_s": 0.8, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
    ev = []
    svc = AgentService(sim, AgentTools(sim, ev.append), ev.append, root=tmp_path)
    out = svc.run_step_test()
    v = out["verdict"]
    assert [s["dir"] for s in v["segments"]] == ["down", "up", "up", "down"]
    assert sum(1 for s in v["segments"] if s.get("ok")) >= 3, v["segments"]
    assert v["steady"]["reason"] in ("steady", "still_drifting", "oscillating", "warming_up")
    assert v["asymmetry"] is not None
    r = svc.rule_round()                                   # 分阶段：第一步一定动 Kp
    assert r.get("status") == "pending_user_confirmation", r          # 只出提议卡，人确认才写


def test_service_elf_watch(elf, tmp_path, home):
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    shutil.copy(elf, tmp_path / "a.elf")
    (tmp_path / "dzbench.json").write_text(json.dumps({"build": {"elf": "a.elf"}}), encoding="utf-8")
    ev = []
    s = Session(emit=ev.append)
    svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path)
    found = svc.elf_symbols("g_")
    assert [x["name"] for x in found] == ["g_count", "g_speed"] and found[1]["type"] == "f32"
    probe = elfsym.MockProbe({0x20200000: bytearray(struct.pack("<f", 3.0) + b"\0" * 12)})
    r = svc.watch_start([{"name": "g_speed", "type": "f32"}], 5, probe=probe)
    time.sleep(0.05)
    assert svc.watch_stop()["stopped"] and r["fields"][0]["addr"] == "0x20200000"
    assert any(v["g_speed"] == 3.0 for _, v in s.window(10))
    with pytest.raises(elfsym.ElfError):
        svc.watch_start([{"name": "nope"}], 5, probe=probe)
    assert svc.watch is None


def test_service_build_log_feeds_flasher(tmp_path, home):
    """v0.7.0 审计发现：编译结果从没交给烧录器，build_ok 前置条件永远不满足。现在 build / build_log 都会登记。"""
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "Objects").mkdir()
    img = tmp_path / "Objects" / "car.axf"; img.write_bytes(b"\x01" * 64)
    (tmp_path / "link_schema.json").write_text(json.dumps({"hash": "12345678"}), encoding="utf-8")
    proj = tmp_path / "car.uvprojx"; proj.write_text("", encoding="utf-8")
    (tmp_path / "dzbench.json").write_text(json.dumps({"build": {"keil_project": "car.uvprojx", "image": "Objects/car.axf",
        "link_schema": "link_schema.json"}, "flash": {"target": "stm32f407vg"}}), encoding="utf-8")
    log = proj.with_suffix(".dzbench_build.log")
    log.write_text('Program Size: Code=100 RO-data=0 RW-data=0 ZI-data=0\n"car.axf" - 0 Error(s), 0 Warning(s).', encoding="utf-8")
    ev = []
    s = Session(emit=ev.append)
    svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path)
    r = svc.build_log()
    assert r["ok"] and r["flash_ready"] is True
    assert svc.flasher.last_build["schema_hash"] == 0x12345678
    assert next(p for p in svc.flasher.preconditions() if p["name"] == "build_ok")["ok"]
    os.utime(log, (time.time() + 600, time.time() + 600))       # 日志和镜像差 10 分钟：不登记
    svc.flasher.last_build = None
    assert svc.build_log()["flash_ready"] != True and svc.flasher.last_build is None
    with pytest.raises(Exception):
        svc.build()                                               # 没配 keil_uv4：明确报错


@pytest.mark.needs_sim
def test_sim_sweep_and_bode_predict(sim, tmp_path, home):
    """仿真板闭环扫频：低频增益≈1、高频衰减、相位滞后随频率增加；计算器给出裕度。"""
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 1.0, "y": "spd_a", "sp": "sp_a",
        "sweep": {"f0": 0.5, "f1": 4.0, "n": 4, "settle_cycles": 1, "cycles": 3}}}), encoding="utf-8")
    ev = []
    svc = AgentService(sim, AgentTools(sim, ev.append), ev.append, root=tmp_path)
    out = svc.gate("run_sweep_test", {}, svc.run_sweep_test)          # 仿真里 log 级，直接跑
    pts = out["points"]
    assert len(pts) >= 3 and not out["errors"], out
    assert 0.5 < pts[0]["gain"] < 1.5, pts[0]
    assert pts[-1]["phase"] < pts[0]["phase"]
    assert any(e["type"] == "sweep_result" for e in ev)
    p = svc.bode_predict(K=2.0, tau=0.3, L=0.02, kp=1.0, ki=2.0)
    assert p["phase_margin_deg"] > 0 and p["bandwidth_hz"] > 0


@pytest.mark.needs_sim
def test_prearm_and_one_shot_card(sim, tmp_path, home, monkeypatch):
    """解锁前检查：正常通过；增益回读不一致 / 急停 → 拒绝；确认卡一次性、过期不执行。"""
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    from dzbench import session as _session
    from dzbench.agent import risk
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 0.6, "pre_s": 0.3, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
    ev = []
    svc = AgentService(sim, AgentTools(sim, ev.append), ev.append, root=tmp_path)
    time.sleep(0.3)
    pa = svc.prearm()
    assert pa["ok"], pa
    assert {"link", "channels", "env", "readback"} <= set(pa["checked"])
    k = next(iter(svc._gains()))
    real = sim.params[k]
    sim.params[k] = real + 1.0                                   # 侧车记录和板上不一致（模拟板子被复位）
    assert any(k in f for f in svc.prearm()["failed"])
    sim.params[k] = real
    # 实机分级：确认卡 + 预览带 prearm；一次性；过期拒绝
    monkeypatch.setattr(risk, "tier", lambda tool, s: risk.HUMAN)
    r = svc.gate("run_step_test", {}, svc.run_step_test)
    card = [e for e in ev if e["type"] == "agent_action"][-1]
    assert card["preview"]["prearm"]["ok"]
    svc.actions[r["action_id"]]["t"] -= svc.ARM_TTL_S + 1
    with pytest.raises(_session.LinkError) as e:
        svc.action_decide(r["action_id"], True)
    assert e.value.code == "arm_expired"
    with pytest.raises(_session.LinkError):
        svc.action_decide(r["action_id"], True)                   # 已消耗：不能再点一次
    sim.tx_locked = True
    r = svc.gate("run_step_test", {}, svc.run_step_test)
    assert "急停" in [e for e in ev if e["type"] == "agent_action"][-1]["preview"]["error"]
    with pytest.raises(_session.LinkError) as e:
        svc.action_decide(r["action_id"], True)
    assert e.value.code == "prearm"
    sim.tx_locked = False


@pytest.mark.needs_sim
def test_sim_as_hw_step_test_needs_arm_card_and_prearm(home, tmp_path):
    """sim:car_2wd+hw：同一个仿真程序，但分级按实板 —— 阶跃实验变成确认卡，预览带 pre-arm 检查，点执行才跑。"""
    if os.name == "nt" or not shutil.which("make") or not shutil.which("cc"):
        pytest.skip("host-sim --stream 需要 POSIX + make + cc")
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    s = Session(emit=lambda e: None)
    s.connect("sim:car_2wd+hw", 115200, log=False)
    try:
        t0 = time.monotonic()
        while s.schema_hash is None and time.monotonic() - t0 < 5:
            time.sleep(0.05)
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
            "high": [0.4, 0], "hold_s": 1.0, "pre_s": 0.3, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
        ev = []
        svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path)
        assert not svc.sim
        r = svc.gate("run_step_test", {}, svc.run_step_test)
        assert r["status"] == "pending_human_click"
        card = [e for e in ev if e["type"] == "agent_action"][-1]
        assert "prearm" in json.dumps(card["preview"], ensure_ascii=False)
        out = svc.action_decide(card["id"], True)
        assert out["status"] != "rejected", out
    finally:
        s.disconnect()


def test_steady_state_four_segment_baseline_is_previous_segment():
    """复现 Windows run 41172197090：四段实验的最后一跳（SP+Δ → SP）基线若取全部历史，中位数 ≈ SP → 幅度 0 → too_little_motion。
    粗时钟（15.6 ms 量化）采样、一阶滞后；基线只取上一段后半就判得出稳态。"""
    from dzbench.tuning.identify import steady_state
    hold, dt, q = 0.8, 0.02, 0.015625
    t, y, sp, yy = [], [], [], 0.4
    for i in range(int(5 * hold / dt)):
        tt = round(i * dt / q) * q                       # Windows 时钟粒度
        s = [0.4, 0.3, 0.4, 0.5, 0.4][min(4, int(i * dt / hold))]
        yy += (s - yy) * 0.25
        t.append(tt); y.append(yy); sp.append(s)
    k = max(i for i in range(1, len(sp)) if sp[i] != sp[i - 1])
    old = steady_state(t, y, t_step=t[k], window_s=0.26, span_ref=0.1)
    assert old["reason"] == "too_little_motion"          # 修之前的行为（不给 base_s）
    new = steady_state(t, y, t_step=t[k], window_s=0.26, span_ref=0.1, base_s=hold / 2)
    assert new["reason"] in ("steady", "still_drifting") and new["amplitude"] > 0.05
