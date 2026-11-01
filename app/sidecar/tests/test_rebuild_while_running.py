"""重编仿真板时旧 elf 还在跑：不能 Text file busy（链接写同目录临时文件再 rename）。"""
from __future__ import annotations

import os
import subprocess

import pytest

from dzbench.transport import sim_elf, sim_root

pytestmark = pytest.mark.needs_sim


def _make(app):
    return subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={app}"], cwd=sim_root(), capture_output=True, text=True)


def test_rebuild_while_old_elf_running():
    app = "car_2wd"
    assert _make(app).returncode == 0
    elf = sim_elf(app)
    p = subprocess.Popen([str(elf), "--stream", "1"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ino = elf.stat().st_ino
        os.utime(elf, (0, 0))                     # 让 elf 比 .o 旧 → 必须重新链接
        r = _make(app)
        assert r.returncode == 0, r.stderr[-800:]
        assert "Text file busy" not in r.stderr
        assert elf.stat().st_ino != ino and elf.stat().st_mtime > 0   # 换了新文件（rename），不是原地覆写
        assert p.poll() is None                   # 旧进程没被打断
        assert not list(elf.parent.glob(elf.name + ".tmp*"))
    finally:
        p.stdin.close()
        p.kill()
        p.wait()


def test_exec_during_relink_never_text_file_busy():
    """另一个进程在同一工作树重链 elf 时启动仿真板：路径上只会是完整的旧文件或新文件，不会是正在写的文件（ETXTBSY）。"""
    import threading
    import time
    app = "car_2wd"
    assert _make(app).returncode == 0
    elf = sim_elf(app)
    stop, errs, builds = threading.Event(), [], []

    def rebuild():
        while not stop.is_set():
            os.utime(elf, (0, 0))
            builds.append(_make(app).returncode)

    t = threading.Thread(target=rebuild)
    t.start()
    try:
        t_end = time.monotonic() + 8
        while time.monotonic() < t_end:
            try:
                p = subprocess.Popen([str(elf), "--stream", "1"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                p.kill()
                p.wait()
            except OSError as e:
                errs.append(e)
    finally:
        stop.set()
        t.join()
    assert len(builds) >= 3 and all(rc == 0 for rc in builds)
    assert not errs, errs[:3]
