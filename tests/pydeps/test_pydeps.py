#!/usr/bin/env python3
"""#112：离线依赖清单齐全、打包脚本离线装、doctor 输出格式、缺包时中文提示 + 离线命令（不联网）。"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import pydeps  # noqa: E402

NEED = {"control", "scipy", "numpy", "sysidentpy", "uncertainties"}
fails = []
m = pydeps.manifest()
if not NEED <= set(m):
    fails.append(f"wheelhouse 清单缺 {sorted(NEED - set(m))}")
if any(not v for v in m.values()):
    fails.append(f"wheelhouse 清单有没钉版本的包：{[k for k, v in m.items() if not v]}")
pk = (ROOT / "tools" / "package_windows.sh").read_text(encoding="utf-8")
for s in ("tools/wheelhouse.txt", "pip download", "--no-index --find-links"):
    if s not in pk:
        fails.append(f"package_windows.sh 缺 {s!r}")
for wf in ("ci.yml", "app-windows.yml"):
    if "tools/wheelhouse.txt" not in (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8"):
        fails.append(f"{wf} 没装 tools/wheelhouse.txt")
for tool in ("plantmodel.py", "randplant.py"):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "doctor"], capture_output=True, text=True,
                       env={"DZ_WHEELHOUSE": "/opt/wh", "PATH": "/usr/bin:/bin"})
    d = json.loads(r.stdout)
    if set(d) != {"ok", "missing", "install_cmd"} or r.returncode != (0 if d["ok"] else 1):
        fails.append(f"{tool} doctor 格式/退出码不对：{r.stdout!r} rc={r.returncode}")
    if "--no-index" not in d["install_cmd"] or "/opt/wh" not in d["install_cmd"] or "http" in d["install_cmd"]:
        fails.append(f"{tool} install_cmd 不是离线命令：{d['install_cmd']}")
    if not d["ok"]:
        fails.append(f"本机缺依赖 {d['missing']}（测试环境应装齐 tools/wheelhouse.txt）")
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pydeps; pydeps.require('dz_no_such_pkg')",
                    str(ROOT / "tools")], capture_output=True, text=True)
if r.returncode == 0 or "缺少 Python 依赖" not in r.stderr or "--no-index" not in r.stderr or "Traceback" in r.stderr:
    fails.append(f"缺包提示不对：{r.stderr!r}")
for f in fails:
    print("✗ [pydeps]", f)
if not fails:
    print("✓ 离线依赖：清单含 5 个钉版本包，打包离线装，doctor JSON {ok, missing, install_cmd}，缺包中文提示")
sys.exit(1 if fails else 0)
