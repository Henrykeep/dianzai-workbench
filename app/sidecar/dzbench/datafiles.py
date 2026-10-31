"""随安装包分发的数据文件（docs/dev/*.json）启动自检：找不到 / 版本不认识 → 进度阻塞项 data_file_missing（fix_action reinstall），
不再静默给空提示。查找顺序：安装包解包目录（PyInstaller _MEIPASS）→ DZBENCH_REPO → 本仓库根。
CLI：python -m dzbench selfcheck-data（缺文件退出 1），app-windows CI 在安装目录里跑。"""
from __future__ import annotations

import json
import os
import pathlib
import sys

REL = pathlib.Path("docs") / "dev"
# 文件名 → (必需, 认的 schema_version, 中文名)。reason_codes.json 生成后自动纳入检查（未生成前不算缺）。
FILES = {"roles.json": (True, 1, "参数角色取值表"),
         "reason_codes.json": (False, 1, "原因码表")}


def roots() -> list[pathlib.Path]:
    out = []
    if getattr(sys, "_MEIPASS", None):
        out.append(pathlib.Path(sys._MEIPASS))
    if os.environ.get("DZBENCH_REPO"):
        out.append(pathlib.Path(os.environ["DZBENCH_REPO"]))
    out.append(pathlib.Path(__file__).resolve().parents[3])
    return out


def find(name: str) -> pathlib.Path | None:
    for r in roots():
        f = r / REL / name
        if f.is_file():
            return f
    return None


def load(name: str) -> tuple[dict | None, dict | None]:
    """→ (内容, 问题)。问题 = {reason:'data_file_missing', file, message_zh, fix_action:'reinstall'}。"""
    req, ver, zh = FILES[name]
    f = find(name)

    def bad(msg):
        return None, {"reason": "data_file_missing", "file": str(REL / name), "message_zh": msg, "fix_action": "reinstall"}
    if f is None:
        return bad(f"{zh} {REL.as_posix()}/{name} 没找到，安装包可能不完整，请重新安装工作台")
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return bad(f"{zh} {name} 读不出来或不是合法 JSON，请重新安装工作台")
    if not isinstance(d, dict) or d.get("schema_version") != ver:
        v = d.get("schema_version") if isinstance(d, dict) else None
        return bad(f"{zh} {name} 的版本 {v!r} 本地服务不认识（只认 {ver}），请重新安装同一版本的工作台")
    return d, None


def check() -> list[dict]:
    out = []
    for name, (req, _, _) in FILES.items():
        if not req and find(name) is None:
            continue
        _, p = load(name)
        if p:
            out.append(p)
    return out


def main() -> int:
    probs = check()
    for name in FILES:
        f = find(name)
        if f is None and not FILES[name][0]:
            print(f"- {name}：可选，尚未生成")
            continue
        print(f"{'✓' if f and not any(p['file'].endswith(name) for p in probs) else '✗'} {name}：{f or '没找到'}")
    for p in probs:
        print("✗ " + p["message_zh"], file=sys.stderr)
    return 1 if probs else 0
