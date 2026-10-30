"""调试后端（dzbench/probes.py）：假 openocd / JLinkExe / probe-rs 走真实后端代码；ST-Link 与 DAPLink 两种探针都过。"""
import os
import pathlib
import socket

import pytest

from dzbench import probes
from dzbench.flash import FlashError

FAKE = pathlib.Path(__file__).parent / "fakeprobes"


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "probe.log"; p.write_text("")
    monkeypatch.setenv("FAKEPROBE_LOG", str(p))
    monkeypatch.setenv("PATH", str(FAKE) + os.pathsep + os.environ["PATH"])
    return p


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.mark.skipif(os.name == "nt", reason="假探针是 POSIX 脚本")
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


@pytest.mark.skipif(os.name == "nt", reason="假探针是 POSIX 脚本")
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
