"""CubeMX 无头生成：用假 STM32CubeMX（读 -q 脚本、在 project path 下写 Core/Src/main.c）验证脚本内容与调用；没装时退回合成。"""
import pathlib

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


# ---- tools-integration：上游 process.py（杀进程树）+ CubeIDE 无头编译 + 假安装目录发现 + 工具声明 ----
import sys  # noqa: E402

import stm32_discovery as D  # noqa: E402

FAKE_SLOW = "import time\ntime.sleep(60)\n"
FAKE_CUBEIDE = """import pathlib, sys
a = sys.argv[1:]
pathlib.Path(a[a.index("-data") + 1], "args.txt").write_text("\\n".join(a))
print("main.c:1: error: boom" if "FAIL" in a[a.index("-import") + 1] else "Build Finished")
sys.exit(1 if "FAIL" in a[a.index("-import") + 1] else 0)
"""


def test_generate_timeout_kills_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBEMX_PATH", str(write_fake(tmp_path / "STM32CubeMX", FAKE_SLOW)))
    ioc = tmp_path / "p" / "a.ioc"; ioc.parent.mkdir(); ioc.write_text("")
    r = cubemx.generate(ioc, timeout=1)
    assert not r["ok"] and r["reason_code"] == "tool_timeout"


def test_cubeide_build_command_and_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBEIDE_PATH", str(write_fake(tmp_path / "stm32cubeidec", FAKE_CUBEIDE)))
    monkeypatch.setattr(cubemx.tempfile, "gettempdir", lambda: str(tmp_path))
    ok = tmp_path / "Good"; ok.mkdir()
    r = cubemx.build(ok, "Release", clean=True)
    assert r["ok"], r
    args = (tmp_path / "dz_cubeide_ws" / "args.txt").read_text().splitlines()
    assert args[-2:] == ["-cleanBuild", "Good/Release"] and "org.eclipse.cdt.managedbuilder.core.headlessbuild" in args
    bad = tmp_path / "FAIL"; bad.mkdir()
    r = cubemx.build(bad)
    assert not r["ok"] and r["errors"] == ["main.c:1: error: boom"]


def test_missing_cubeide(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBEIDE_PATH", str(tmp_path / "nope"))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(D, "_known_roots", lambda: [])
    monkeypatch.setattr(D, "_registry_roots", lambda: [])
    D.reset_cache()
    assert cubemx.build(tmp_path)["reason_code"] == "missing_cubeide"
    assert cubemx.status("cubeide_build") == {"status": "missing_dep", "reason_code": "missing_cubeide"}


def test_discovery_finds_fake_install_dir(tmp_path, monkeypatch):
    for k in ("CUBEIDE_PATH", "CUBEMX_PATH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    suf = ".exe" if sys.platform == "win32" else ""
    exe = tmp_path / "STM32CubeIDE_1.16.0" / "STM32CubeIDE" / ("stm32cubeidec" + suf)
    exe.parent.mkdir(parents=True); exe.write_text(""); exe.chmod(0o755)
    monkeypatch.setattr(D, "_known_roots", lambda: [str(tmp_path)])
    monkeypatch.setattr(D, "_registry_roots", lambda: [])
    D.reset_cache()
    assert pathlib.Path(cubemx.find_cubeide()) == exe
    D.reset_cache()


def test_tool_declarations():
    from dzbench import toolreg
    ids = {t["id"]: t for t in toolreg.tool_list()["tools"]}
    assert {"cubemx_generate", "cubeide_build"} <= set(ids)
    for t in ids.values():
        assert t["stage"] in toolreg.STAGES and t["status"] in ("available", "missing_dep", "needs_board")
        if t["status"] != "available":
            assert t["reason_code"] and t["fix_action"]
    assert toolreg.tool_get("cubeide_build")["run"]["op"] == "cubeide_build"
