"""调试后端（dzbench/probes.py）：假 openocd / JLinkExe / probe-rs 走真实后端代码；ST-Link 与 DAPLink 两种探针都过。"""
import os
import pathlib
import socket

import pytest

from dzbench import probes
from dzbench.flash import FlashError

FAKE = pathlib.Path(__file__).parent / "fakeprobes"   # Python 假工具；Windows 上 shutil.which 找同名 .cmd 包装


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "probe.log"; p.write_text("")
    monkeypatch.setenv("FAKEPROBE_LOG", str(p))
    monkeypatch.setenv("PATH", str(FAKE) + os.pathsep + os.environ["PATH"])
    return p


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.mark.parametrize("kind,iface", [("stlink", "interface/stlink.cfg"), ("daplink", "interface/cmsis-dap.cfg")])
def test_openocd_spawn(log, kind, iface):
    be = probes.make_backend({"tool": "openocd", "target": "stm32f407vetx", "probe_kind": kind, "probe": "SN123",
                              "openocd": {"port": free_port()}})
    try:
        assert be.idcode() == 0x2BA01477
        assert be.read(0x20000010, 5) == bytes([0x10, 0x11, 0x12, 0x13, 0x14])
        assert len(be.read(0x20000000, 5000)) == 5000              # 分块
        be.load("/tmp/x.elf", 0x08000000); be.reset()
        assert be.flash_size() == 524288
    finally:
        be.close()
    t = log.read_text()
    assert f"-f {iface}" in t and "target/stm32f4x.cfg" in t and "adapter serial SN123" in t
    assert "tcl program {/tmp/x.elf} verify" in t and "tcl reset run" in t


def test_jlink_and_probe_rs(log):
    j = probes.make_backend({"tool": "jlink", "target": "mspm0g3507"})
    assert j.idcode() == 0x0BC11477 and j.read(0x20200000, 20)[:3] == b"\x00\x01\x02"
    j.load("/tmp/a.bin", 0); j.reset()
    for kind in ("stlink", "daplink"):
        r = probes.make_backend({"tool": "probe-rs", "target": "mspm0g3507", "probe_kind": kind})
        assert r.idcode() == 0x0BC11477 and r.read(0x20200000, 4) == b"\x00\x01\x02\x03"
        r.load("/tmp/a.bin", 0); r.reset()
    t = log.read_text()
    assert "-device MSPM0G3507" in t and "loadfile \"/tmp/a.bin\" 0x00000000" in t and "mem8 0x20200000, 0x14" in t
    assert "--chip MSPM0G3507" in t and "--binary-format bin" in t


def test_errors(monkeypatch):
    with pytest.raises(FlashError) as e:
        probes.make_backend({"tool": "jlink", "target": "mspm0g3507", "probe_kind": "stlink"})
    assert e.value.code == "probe_kind"
    with pytest.raises(FlashError):
        probes.make_backend({"tool": "nope", "target": "x"})
    with pytest.raises(FlashError) as e:
        probes.chip_name("openocd", "gd32f303", {})
    assert "target_cfg" in e.value.fix
    monkeypatch.setenv("PATH", "/nonexistent")
    st = probes.tool_status({"tool": "probe-rs"})
    assert not st["ok"] and "cargo install" in st["fix"]


def test_list_probes_per_backend(log):
    r = probes.list_probes_for("probe-rs")
    assert [(p["uid"], p["kind"]) for p in r["probes"]] == [("0483:374b:066DFF555", "stlink"), ("0d28:0204:0240000034", "daplink")]
    j = probes.list_probes_for("jlink")
    assert j["probes"][0]["uid"] == "260112345" and j["probes"][0]["kind"] == "jlink"


def test_probe_config_roundtrip(home, tmp_path, monkeypatch):
    import json
    from dzbench import config as cfg_mod, snapshots
    from dzbench.agent.service import AgentService
    from dzbench.flash import Flasher
    monkeypatch.setattr(probes, "list_probes_for", lambda tool, f=None: {"via": tool, "probes": []})
    (tmp_path / "dzbench.json").write_text(json.dumps({"flash": {"target": "stm32f407vetx"}}))

    class GW: root = tmp_path
    svc = AgentService.__new__(AgentService)
    svc.gw, svc.cfg = GW(), cfg_mod.load(tmp_path)
    svc.flasher = Flasher(None, svc.cfg)
    r = svc.probe_config_set({"tool": "openocd", "probe_kind": "daplink", "probe": "0240000034"})
    assert (r["tool"], r["probe_kind"], r["probe"]) == ("openocd", "daplink", "0240000034") and r["project_overrides"] == []
    assert svc.flasher.cfg["flash"]["tool"] == "openocd"                 # Flasher 看到的是同一个 dict
    m = json.loads((snapshots.base_dir() / "machine.json").read_text())
    assert m["flash"] == {"tool": "openocd", "probe_kind": "daplink", "probe": "0240000034"}
    svc.probe_config_set({"probe": ""})                                   # 清空 = 回默认
    assert "probe" not in json.loads((snapshots.base_dir() / "machine.json").read_text())["flash"]
    with pytest.raises(Exception):
        svc.probe_config_set({"tool": "keil"})
