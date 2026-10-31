"""随安装包分发的数据文件（docs/dev/*.json）启动自检：找不到 / 版本不认识 → 进度阻塞项 data_file_missing（fix_action reinstall），
不再静默给空提示。查找顺序：安装包解包目录（PyInstaller _MEIPASS）→ DZBENCH_REPO → 本仓库根。
CLI：python -m dzbench selfcheck-data（缺文件退出 1），app-windows CI 在安装目录里跑。"""
from __future__ import annotations

import hashlib
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

    def bad(msg, status="invalid"):
        return None, {"reason": "data_file_missing", "file": (REL / name).as_posix(), "status": status,
                      "message_zh": msg, "fix_action": "reinstall"}
    if f is None:
        return bad(f"{zh} {REL.as_posix()}/{name} 没找到，安装包可能不完整，请重新安装工作台，装好后点『运行自检』确认", "missing")
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


def report() -> dict:
    """唯一的检查函数：CLI、独立脚本 selfcheck_data.py 和 op selfcheck_data 都用它。
    → {ok, items:[{file, status:'ok'|'missing'|'invalid', message_zh, fix_action}]}；提示里不出现命令行。"""
    items = []
    for name, (req, _, zh) in FILES.items():
        if not req and find(name) is None:
            items.append({"file": (REL / name).as_posix(), "status": "ok", "message_zh": f"{zh}：可选，尚未提供", "fix_action": None})
            continue
        _, p = load(name)
        items.append({k: p[k] for k in ("file", "status", "message_zh", "fix_action")} if p else
                     {"file": (REL / name).as_posix(), "status": "ok", "message_zh": f"{zh}：正常", "fix_action": None})
    return {"ok": all(i["status"] == "ok" for i in items), "items": items}


def main() -> int:
    r = report()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["ok"] else 1


def tables() -> dict:
    """hello 里给界面的 data_tables：{roles|reason_codes: {sha256（原始字节）, content（原样解析的 JSON）} | null}。
    缺失 / 不合法 / 版本不认识 → null（同时进度里出 data_file_missing 阻塞）。"""
    out = {}
    for name in FILES:
        key = name[:-5]
        f = find(name)
        d, prob = load(name) if f else (None, True)
        if prob or f is None:
            out[key] = None
            continue
        try:
            raw = f.read_bytes()
        except OSError:
            out[key] = None
            continue
        out[key] = {"sha256": hashlib.sha256(raw).hexdigest(), "content": d}
    return out
