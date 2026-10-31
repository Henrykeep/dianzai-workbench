#!/usr/bin/env python3
"""芯台自检（安装目录 xintai-selfcheck.bat / 仓库根 xintai-selfcheck.sh 调它）。只用标准库起步：
先跑依赖自检（tools/pydeps.py doctor），不通过就打印中文原因和办法后退出（退出码 1），不再往下跑、不甩 Traceback；
通过后检查数据文件（docs/dev/roles.json、docs/dev/reason_codes.json），侧车有 selfcheck-data 命令时再跑 `python -m dzbench selfcheck-data`。
全部通过退出码 0。
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


def main() -> int:
    print(f"芯台自检（Python {sys.version.split()[0]}，{sys.executable}）")
    print("== 1/3 Python 依赖")
    d = pydeps.doctor()
    if not d["ok"]:
        print(f"[失败] {d['message_zh']}")
        if d.get("install_cmd"):
            print(f"  离线安装命令：{d['install_cmd']}")
        print("依赖没就绪，后面的检查先不跑。按上面的办法处理后再运行自检。")
        return 1
    print("[通过] 五个依赖都能导入")
    print("== 2/3 数据文件")
    fail = 0
    for name, check in (("roles.json", lambda j: j.get("schema_version") == 1 and len(j.get("roles") or []) == 6
                         and all(r.get("zh") for r in j["roles"])), ("reason_codes.json", lambda j: bool(j))):
        f = ROOT / "docs" / "dev" / name
        try:
            ok = check(json.loads(f.read_text(encoding="utf-8")))
            print(f"[通过] {name}" if ok else f"[失败] {name} 内容不对（{f}）")
        except FileNotFoundError:
            ok = False; print(f"[失败] 缺少 {name}（{f}），安装包可能不完整，请重新安装")
        except ValueError as e:
            ok = False; print(f"[失败] {name} 读不出来：{e}")
        fail |= not ok
    print("== 3/3 本地服务数据自检")
    if not has_selfcheck_data():
        print("[提示] 这一版本地服务还没有 selfcheck-data 自检，跳过")
    else:
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(SIDECAR), os.environ.get("PYTHONPATH", "")])),
                   PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-m", "dzbench", "selfcheck-data"], cwd=str(ROOT.parent), env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0:
            print("[通过] 本地服务数据自检" + (f"\n{out}" if out else ""))
        else:
            fail = 1
            tail = "\n".join(out.splitlines()[-15:])
            print(f"[失败] 本地服务数据自检退出码 {r.returncode}" + (f"：\n{tail}" if tail else ""))
    print("自检全部通过" if not fail else "自检没通过，请按上面标了[失败]的条目处理")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
