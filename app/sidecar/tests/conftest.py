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


# 第三方 SDK / HAL 不入库（.gitignore），新 worktree 里没有：标 @pytest.mark.needs_third_party("stm32f4xx-hal-driver", ...) 缺了就跳过，
# 而不是红一片；要跑就 tools/fetch_third_party.sh f4 f1 freertos mspm0（CI 与 preflight 都拉全）。
THIRD = pathlib.Path(__file__).resolve().parents[3] / "third_party"


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_sim: 需要 host-sim 仿真板（Windows / 无 make+cc 时跳过）")
    config.addinivalue_line("markers", "needs_third_party(*dirs): 需要 third_party/ 下的 SDK（缺了跳过）")


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="需要 host-sim 仿真板（Windows 或缺 make/cc）")
    for it in items:
        if it.get_closest_marker("needs_sim") and not SIM_OK:
            it.add_marker(skip)
        m = it.get_closest_marker("needs_third_party")
        miss = [d for d in (m.args if m else ()) if not (THIRD / d).is_dir()]
        if miss:
            it.add_marker(pytest.mark.skip(reason=f"缺 third_party/{', '.join(miss)}：tools/fetch_third_party.sh f4 f1 freertos mspm0"))


@pytest.fixture(autouse=True)
def _sim_guard(request, monkeypatch, _hermetic_env):
    if request.node.get_closest_marker("needs_sim"):
        return
    from dzbench import transport
    monkeypatch.setenv("DZBENCH_TEST_NO_SIM", request.node.nodeid)

    def boom(*a, **k):
        raise AssertionError(f"{request.node.nodeid} 起了仿真板却没标 @pytest.mark.needs_sim（Windows CI 会挂）")
    monkeypatch.setattr(transport.SimTransport, "__init__", boom)


@pytest.fixture(autouse=True)
def _hermetic_env(tmp_path_factory, monkeypatch):
    """测试与本机状态无关：清掉 DZBENCH_* / PYOCD_* 环境变量，DZBENCH_HOME 指到空目录
    （不读本机 ~/.dzbench 的 machine.json、LLM Key、快照、器件包）。要用固定目录的测试请求 `home` fixture。"""
    import os
    for k in list(os.environ):
        if k.startswith(("DZBENCH_", "PYOCD_")):
            monkeypatch.delenv(k)
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path_factory.mktemp("dzhome")))


@pytest.fixture(autouse=True)
def _hermetic_pack(tmp_path_factory, monkeypatch, _hermetic_env):
    """测试不依赖本机有没有下过 TI 器件包（CI 的 sidecar-test 不下载）：统一给一个假包，fakepyocd 只记录路径。
    要测“缺包”的用例自己 delenv / 打桩 find_pack。"""
    p = tmp_path_factory.getbasetemp() / "fake_m0.pack"
    if not p.exists():
        p.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    monkeypatch.setenv("DZBENCH_PACK", str(p))
