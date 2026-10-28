"""烧录前置条件 / Keil 日志 / HardFault / ELF 变量 / 分层配置 / 风险分级动作卡（全部离线，假探针）。"""
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
    s = Session(emit=lambda e: None)
    s.connect("sim:car_2wd", 115200, log=False)
    t0 = time.monotonic()
    while s.schema_hash is None and time.monotonic() - t0 < 5:
        time.sleep(0.05)
    yield s
    s.disconnect()


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
