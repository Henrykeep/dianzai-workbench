"""CubeMX 无头生成：用假 STM32CubeMX（读 -q 脚本、在 project path 下写 Core/Src/main.c）验证脚本内容与调用；没装时退回合成。"""
import os
import stat
import sys

import pytest

from dzbench import cubemx

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="假 CubeMX 是 sh 脚本")


def _fake(tmp_path):
    exe = tmp_path / "STM32CubeMX"
    exe.write_text('#!/bin/sh\ncp "$2" "$(dirname "$0")/last_script.txt"\n'
                   'out=$(sed -n "s/^project path //p" "$2")\nmkdir -p "$out/Core/Src" && echo "/* real */" > "$out/Core/Src/main.c"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


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
