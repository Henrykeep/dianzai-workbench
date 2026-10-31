"""xintai-selfcheck.sh 入口：PYTHONPATH 置空；有依赖 → 0；缺依赖的 Python → 非 0、中文原因、无 Traceback。"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SH = ROOT / "xintai-selfcheck.sh"


def _run(py):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DZ_LLM_")}
    env.update(PYTHONPATH="", DZ_NOPAUSE="1", PYTHON=str(py))
    env.pop("PYTHONHOME", None)
    return subprocess.run([str(SH)], cwd=str(ROOT), env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=300)


def test_order_prefers_venv_then_312():
    s = SH.read_text()
    assert "for c in .venv/bin/python python3.12 python3 python" in s


def test_passes_with_deps():
    r = _run(sys.executable)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stdout + r.stderr


def test_fails_chinese_without_deps(tmp_path):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "v")], check=True)
    r = _run(tmp_path / "v" / "bin" / "python")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "缺少" in out and "[失败]" in out, out
    assert "Traceback" not in out, out
