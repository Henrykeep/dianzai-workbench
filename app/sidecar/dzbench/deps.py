"""一键安装缺失依赖（入口 fetch_deps）。

只根据自检（doctor.py）的 fail 项决定做什么，复用仓库已有的安装方式，不另造：
  py_<模块>  → python -m pip install <包>（与 doctor 给的 fix 相同）
  pack       → tools/fetch_third_party.sh m0pack（与 doctor 给的 fix 相同）
其余 fail 项（如 dzbench.json 语法错误、Keil 路径、数据目录不可写）无法自动处理，原样列为 unresolved，附 doctor 的处理建议。
命令固定，不拼接用户输入。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

PIP = {"py_serial": "pyserial", "py_websockets": "websockets", "py_pyocd": "pyocd"}


def plan(items: list[dict], repo: str) -> tuple[list[list[str]], list[dict]]:
    cmds, unresolved = [], []
    for it in items:
        if it.get("level") != "fail":
            continue
        if it["id"] in PIP:
            cmds.append([sys.executable, "-m", "pip", "install", PIP[it["id"]]])
        elif it["id"] == "pack":
            cmds.append(["bash", str(pathlib.Path(repo) / "tools/fetch_third_party.sh"), "m0pack"])
        else:
            unresolved.append({"name": it.get("name"), "fix": it.get("fix", "")})
    return cmds, unresolved


def _run(cmd: list[str], cwd: str) -> dict:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900)
        return {"cmd": " ".join(cmd), "rc": r.returncode, "tail": (r.stdout + r.stderr)[-1500:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"cmd": " ".join(cmd), "rc": -1, "tail": str(e)}


def fetch(items: list[dict], repo: str, runner=_run) -> dict:
    cmds, unresolved = plan(items, repo)
    ran = [runner(c, repo) for c in cmds]
    return {"ran": ran, "ok": all(r["rc"] == 0 for r in ran) and not unresolved, "unresolved": unresolved}
