#!/usr/bin/env python3
"""芯台自检（安装目录 xintai-selfcheck.bat / 仓库根 xintai-selfcheck.sh 调它）。只用标准库起步：
先跑依赖自检（tools/pydeps.py doctor），不通过就打印中文原因和办法后退出（退出码 1），不再往下跑、不甩 Traceback；
通过后检查数据文件（docs/dev/roles.json、docs/dev/reason_codes.json），侧车有 selfcheck-data 命令时再跑 `python -m dzbench selfcheck-data`。
退出码（统一口径，tools/tooljson.py）：0 = 全部检查且通过；1 = 有数据内容不对（selfcheck_failed）；
3 = 缺依赖 / 数据文件缺失 / 有「未检查」的项（missing_dep / data_missing / selfcheck_incomplete）。未检查不算通过。
--json：只输出一段 JSON：统一信封 {tool, stage, state, exit_code, blocks, errors, details}，并保留旧字段
rc / ok / complete / summary_zh / items（items[].status = ok|missing|invalid|unchecked，另加 reason_code）；
绝对路径、子进程输出只放 details。
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


def item_code(i):
    if i["status"] == "ok":
        return None
    if i["status"] == "unchecked":
        return "selfcheck_incomplete"
    if i.get("id") == "python_deps":
        return "missing_dep"
    return "data_missing" if i["status"] == "missing" else "selfcheck_failed"


def errors_of(items):
    """按优先级排：内容不对（1）在前，其次缺依赖/缺文件/未检查（3）；退出码 = 第一条的码。"""
    import tooljson as T
    codes = []
    for c in ("selfcheck_failed", "missing_dep", "data_missing", "selfcheck_incomplete"):
        ids = [i.get("id") for i in items if item_code(i) == c]
        if ids:
            codes.append(T.error(c, items=ids))
    return codes


def summarize(items):
    failed = [i for i in items if i["status"] in ("missing", "invalid")]
    unchecked = [i for i in items if i["status"] == "unchecked"]
    if failed:
        rc = 1 if any(i["status"] == "invalid" and i.get("id") != "python_deps" for i in failed) else 3
        return rc, f"自检没通过：{len(failed)} 项失败" + (f"，{len(unchecked)} 项未检查" if unchecked else "")
    if unchecked:
        return 3, f"自检未完成：{len(unchecked)} 项未检查"
    return 0, "自检全部通过"


LABEL = {"ok": "[通过]", "missing": "[失败]", "invalid": "[失败]", "unchecked": "[未检查]"}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Windows 管道/重定向时 stdout 是 cp1252，打中文会 UnicodeEncodeError（app-windows 41273621192）。
    # 不靠 PYTHONIOENCODING：双击 .bat / Tauri 调用时没有这个环境变量。
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    items = run_checks()
    rc, summary = summarize(items)
    if "--json" in argv:
        import tooljson as T
        volatile = ("path", "detail", "rc", "install_cmd")   # 绝对路径 / 子进程输出 → details，保证同输入字节一致
        pub = [{k: v for k, v in i.items() if k not in volatile} | {"reason_code": item_code(i)} for i in items]
        rows = [[i["id"], i["status"], item_code(i)] for i in items]
        _, env = T.envelope("selfcheck", "调试", errors_of(items), [T.table(["id", "status", "reason_code"], rows)],
                            {"python": sys.executable, "items": {i["id"]: {k: i[k] for k in volatile if k in i} for i in items}})
        assert env["exit_code"] == rc, (env["exit_code"], rc)
        env |= {"rc": rc, "ok": rc == 0, "complete": not any(i["status"] == "unchecked" for i in items),
                "summary_zh": summary, "items": pub}
        T.emit(env)  # 纯 ASCII + 排序键：任何控制台编码下都能被 ConvertFrom-Json 正确读
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
