import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------- 仿真板门禁
# 用到 host-sim 仿真板的测试统一标 @pytest.mark.needs_sim（或模块级 pytestmark）。
# Windows（mingw 没有 asan/ubsan、Makefile 用了 POSIX 命令）或没有 make/cc 时统一跳过。
# 没标却起了仿真板 → 直接失败，免得只在 Windows CI 上才暴露（v0.8.0 的 app-windows 就是这样挂的）。
import os  # noqa: E402
import shutil  # noqa: E402

SIM_OK = os.name != "nt" and bool(shutil.which("make")) and bool(shutil.which("cc"))


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_sim: 需要 host-sim 仿真板（Windows / 无 make+cc 时跳过）")


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="需要 host-sim 仿真板（Windows 或缺 make/cc）")
    for it in items:
        if it.get_closest_marker("needs_sim") and not SIM_OK:
            it.add_marker(skip)


@pytest.fixture(autouse=True)
def _sim_guard(request, monkeypatch):
    if request.node.get_closest_marker("needs_sim"):
        return
    from dzbench import transport
    monkeypatch.setenv("DZBENCH_TEST_NO_SIM", request.node.nodeid)

    def boom(*a, **k):
        raise AssertionError(f"{request.node.nodeid} 起了仿真板却没标 @pytest.mark.needs_sim（Windows CI 会挂）")
    monkeypatch.setattr(transport.SimTransport, "__init__", boom)
