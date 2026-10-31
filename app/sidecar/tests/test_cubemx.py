"""CubeMX 无头生成：用假 STM32CubeMX（读 -q 脚本、在 project path 下写 Core/Src/main.c）验证脚本内容与调用；没装时退回合成。"""
import pytest

from conftest import write_fake
from dzbench import cubemx

FAKE_CUBEMX = """import os, pathlib, shutil, sys
sp = sys.argv[2]                                                   # STM32CubeMX -q <脚本>
shutil.copy(sp, os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_script.txt"))
out = next(l[len("project path "):] for l in open(sp, encoding="utf-8").read().splitlines() if l.startswith("project path "))
src = pathlib.Path(out, "Core", "Src"); src.mkdir(parents=True, exist_ok=True)
(src / "main.c").write_text("/* real */\\n")
"""


def _fake(tmp_path):
    return write_fake(tmp_path / "STM32CubeMX", FAKE_CUBEMX)


def test_generate_with_fake_cubemx(tmp_path, monkeypatch):
    exe = _fake(tmp_path)
    monkeypatch.setenv("CUBEMX_PATH", str(exe))
    ioc = tmp_path / "proj" / "b1.ioc"; ioc.parent.mkdir(); ioc.write_text("Mcu.UserName=STM32F407VETx\n")
    r = cubemx.generate(ioc)
    assert r["ok"], r
    s = (tmp_path / "last_script.txt").read_text()
    assert s.splitlines() == [f"config load {ioc}", "project toolchain MDK-ARM V5", "project name proj",
                              f"project path {ioc.parent}", "project generate", "exit"]


def test_missing_cubemx_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBEMX_PATH", str(tmp_path / "nope"))
    monkeypatch.setenv("PATH", str(tmp_path))
    r = cubemx.generate(tmp_path / "x.ioc")
    assert not r["ok"] and "CubeMX" in r["why"]
