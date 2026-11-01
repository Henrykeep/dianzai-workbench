"""#157 xintai-selfcheck.sh 选解释器：跳过缺依赖的 python3.12，挑第一个依赖齐全的；都不齐 → 中文列缺什么、退出码 3。
用 PATH 上的假解释器（shim）模拟，不依赖本机装了哪些 Python。"""
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SH = ROOT / "xintai-selfcheck.sh"
TOOLS = ["bash", "sh", "sed", "tr", "grep", "tail", "timeout", "dirname", "cat", "env"]


def _bin(tmp, shims):
    d = tmp / "bin"
    d.mkdir()
    for t in TOOLS:
        p = shutil.which(t)
        if p:
            (d / t).symlink_to(p)
    for name, body in shims.items():
        f = d / name
        f.write_text("#!/bin/sh\n" + body + "\n")
        f.chmod(0o755)
    return d


def _nodeps_venv(tmp):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp / "v")], check=True)
    return tmp / "v" / "bin" / "python"


def _run(bindir, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DZ_LLM_") and k != "PYTHON"}
    env.update(PATH=str(bindir), PYTHONPATH="", DZ_NOPAUSE="1", **extra)
    env.pop("PYTHONHOME", None)
    return subprocess.run([str(SH)], cwd=str(ROOT), env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=300)


def test_skips_312_without_deps(tmp_path):
    bad = _nodeps_venv(tmp_path)
    log = tmp_path / "ran"
    d = _bin(tmp_path, {
        "python3.12": f'exec "{bad}" "$@"',
        # 依赖齐全的 python3；跑 selfcheck.py 时留个记号再交给真解释器
        "python3": f'case "$1" in tools/selfcheck.py) echo good > "{log}";; esac; exec "{sys.executable}" "$@"',
    })
    r = _run(d)
    out = r.stdout + r.stderr
    assert log.read_text().strip() == "good", out
    assert r.returncode in (0, 3) and "[未完成] 找到了 Python" not in out, out
    assert "Traceback" not in out


def test_none_complete_exit3_chinese(tmp_path):
    bad = _nodeps_venv(tmp_path)
    d = _bin(tmp_path, {"python3.12": f'exec "{bad}" "$@"', "python3": f'exec "{bad}" "$@"',
                        "python3.11": "exit 127"})
    r = _run(d)
    out = r.stdout + r.stderr
    assert r.returncode == 3, out
    assert "[未完成]" in out and "python3.12" in out and "python3" in out and "缺：" in out, out
    assert "serial" in out and "yaml" in out, out
    assert "python3.11" in out and "无法运行" in out, out
    assert "PYTHON=/path/to/python ./xintai-selfcheck.sh" in out and "--no-index" in out, out
    assert "Traceback" not in out


def test_python_env_honored_first(tmp_path):
    log = tmp_path / "ran"
    d = _bin(tmp_path, {"python3.12": f'echo wrong > "{log}"; exec "{sys.executable}" "$@"'})
    mine = tmp_path / "mypy"
    mine.write_text(f'#!/bin/sh\ncase "$1" in tools/selfcheck.py) echo mine > "{log}";; esac\nexec "{sys.executable}" "$@"\n')
    mine.chmod(0o755)
    r = _run(d, PYTHON=str(mine))
    assert log.read_text().strip() == "mine", r.stdout + r.stderr


def test_probe_timeout_does_not_hang(tmp_path):
    d = _bin(tmp_path, {"python3.12": "sleep 60", "python3": f'exec "{sys.executable}" "$@"'})
    r = _run(d)
    assert r.returncode in (0, 3) and "[未完成] 找到了 Python" not in r.stdout, r.stdout + r.stderr
