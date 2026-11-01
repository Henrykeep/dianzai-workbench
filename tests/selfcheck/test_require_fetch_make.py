"""干净工作区没 make fetch 就 make check / make test：第一时间中文提示缺 CMSIS_6、退出非零。"""
import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
MSG = "缺少第三方依赖 CMSIS_6，请先运行 make fetch"


def _clean_tree(tmp):
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    for f in filter(None, files):
        rel = f.decode()
        if rel.startswith("third_party/"):
            continue
        src = ROOT / rel
        if src.is_file():
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return tmp


def test_make_check_and_test_without_fetch(tmp_path):
    t = _clean_tree(tmp_path / "repo")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DZ_LLM_") and not k.startswith("MAKE")}
    for target in ("check", "test"):
        r = subprocess.run(["make", target], cwd=t, env=env, capture_output=True, text=True, timeout=300)
        assert r.returncode != 0, r.stdout + r.stderr
        assert MSG in r.stderr, r.stdout + r.stderr
