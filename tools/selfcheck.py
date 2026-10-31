#!/usr/bin/env python3
"""芯台自检（安装目录 xintai-selfcheck.bat / 仓库根 xintai-selfcheck.sh 调它）。只用标准库起步：
先跑依赖自检（tools/pydeps.py doctor），不通过就打印中文原因和办法后退出（退出码 1），不再往下跑、不甩 Traceback；
通过后检查数据文件（docs/dev/roles.json、docs/dev/reason_codes.json），侧车有 selfcheck-data 命令时再跑 `python -m dzbench selfcheck-data`。
退出码：0 = 全部检查且通过；1 = 有失败；3 = 未完成（有「未检查」的项、没有失败）。未检查不算通过。
--json：只输出一段 JSON（items[].status = ok|missing|invalid|unchecked），给前端用。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pydeps  # noqa: E402  只用标准库

SIDECAR = ROOT / "app" / "sidecar"


def has_selfcheck_data() -> bool:
    d = SIDECAR / "dzbench"
    return d.is_dir() and any("selfcheck-data" in p.read_text(encoding="utf-8", errors="replace") for p in d.rglob("*.py"))


def _item(iid, name_zh, status, reason_zh="", **extra):
    return dict(id=iid, name_zh=name_zh, status=status, reason_zh=reason_zh, **extra)


def run_checks() -> list[dict]:
    items = []
    d = pydeps.doctor()
    if not d["ok"]:
        st = "invalid" if d.get("reason") in ("python_mismatch", "import_failed") else "missing"
        items.append(_item("python_deps", "Python 依赖", st, d["message_zh"], reason=d.get("reason"),
                           missing=d.get("missing") or [], install_cmd=d.get("install_cmd")))
        why = "Python 依赖没就绪，这一项没法检查"
        for iid, nm in (("roles", "角色数据"), ("reason_codes", "原因码数据"), ("selfcheck_data", "本地服务数据自检")):
            items.append(_item(iid, nm, "unchecked", why))
        return items
    items.append(_item("python_deps", "Python 依赖", "ok"))
    for iid, nm, name, check in (
            ("roles", "角色数据", "roles.json", lambda j: j.get("schema_version") == 1 and len(j.get("roles") or []) == 6
             and all(r.get("zh") for r in j["roles"])),
            ("reason_codes", "原因码数据", "reason_codes.json", lambda j: bool(j))):
        f = ROOT / "docs" / "dev" / name
        try:
            ok = check(json.loads(f.read_text(encoding="utf-8")))
            items.append(_item(iid, nm, "ok", path=str(f)) if ok else
                         _item(iid, nm, "invalid", "数据内容不对，安装包可能不完整，请重新安装", path=str(f)))
        except FileNotFoundError:
            items.append(_item(iid, nm, "missing", "数据文件缺失，安装包可能不完整，请重新安装", path=str(f)))
        except ValueError as e:
            items.append(_item(iid, nm, "invalid", "数据文件读不出来，请重新安装", path=str(f), detail=str(e)))
    if not has_selfcheck_data():
        items.append(_item("selfcheck_data", "本地服务数据自检", "unchecked", "这一版本地服务还没有数据自检功能"))
    else:
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(SIDECAR), os.environ.get("PYTHONPATH", "")])),
                   PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-m", "dzbench", "selfcheck-data"], cwd=str(ROOT.parent), env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = (r.stdout + r.stderr).strip()
        tail = "\n".join(out.splitlines()[-15:])
        items.append(_item("selfcheck_data", "本地服务数据自检", "ok", detail=out) if r.returncode == 0 else
                     _item("selfcheck_data", "本地服务数据自检", "invalid", "本地服务数据自检没通过", rc=r.returncode, detail=tail))
    return items


def summarize(items):
    failed = [i for i in items if i["status"] in ("missing", "invalid")]
    unchecked = [i for i in items if i["status"] == "unchecked"]
    if failed:
        return 1, f"自检没通过：{len(failed)} 项失败" + (f"，{len(unchecked)} 项未检查" if unchecked else "")
    if unchecked:
        return 3, f"自检未完成：{len(unchecked)} 项未检查"
    return 0, "自检全部通过"


LABEL = {"ok": "[通过]", "missing": "[失败]", "invalid": "[失败]", "unchecked": "[未检查]"}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    items = run_checks()
    rc, summary = summarize(items)
    if "--json" in argv:
        print(json.dumps({"rc": rc, "ok": rc == 0, "complete": not any(i["status"] == "unchecked" for i in items),
                          "summary_zh": summary, "python": sys.executable, "items": items}, ensure_ascii=False, indent=1))
        return rc
    print(f"芯台自检（Python {sys.version.split()[0]}，{sys.executable}）")
    for i in items:
        line = f"{LABEL[i['status']]} {i['name_zh']}" + (f"：{i['reason_zh']}" if i["reason_zh"] else "")
        print(line)
        if i.get("install_cmd"):
            print(f"  离线安装命令：{i['install_cmd']}")
        if i["status"] != "ok" and i.get("path"):
            print(f"  位置：{i['path']}")
        if i["status"] == "invalid" and i.get("detail"):
            print("  " + i["detail"].replace("\n", "\n  "))
    print(summary)
    return rc


if __name__ == "__main__":
    sys.exit(main())
