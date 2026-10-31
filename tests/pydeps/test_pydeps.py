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
    if not {"ok", "missing", "install_cmd", "reason", "message_zh", "python"} <= set(d) or r.returncode != (0 if d["ok"] else 1):
        fails.append(f"{tool} doctor 格式/退出码不对：{r.stdout!r} rc={r.returncode}")
    if "--no-index" not in d["install_cmd"] or "/opt/wh" not in d["install_cmd"] or "http" in d["install_cmd"]:
        fails.append(f"{tool} install_cmd 不是离线命令：{d['install_cmd']}")
    if not d["ok"]:
        fails.append(f"本机缺依赖 {d['missing']}（测试环境应装齐 tools/wheelhouse.txt）")
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pydeps; pydeps.require('dz_no_such_pkg')",
                    str(ROOT / "tools")], capture_output=True, text=True)
if r.returncode == 0 or "缺少 Python 依赖" not in r.stderr or "--no-index" not in r.stderr or "Traceback" in r.stderr:
    fails.append(f"缺包提示不对：{r.stderr!r}")
# 自带嵌入版 Python：打包脚本钉版本 + sha256、走 fetch_url、改 ._pth、写 manifest、装进自带解释器
for s in ("python-$PYVER-embed-amd64.zip", "PYEMBED_SHA=", "fetch_url \"$PYEMBED_URL\"", "pyembed.py\" pth",
          "pyembed.py\" manifest", "--target \"$STAGE/python/Lib/site-packages\"", "python\\\\python.exe"):
    if s not in pk:
        fails.append(f"package_windows.sh 缺 {s!r}")
import tempfile  # noqa: E402
import pyembed  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    td = pathlib.Path(td)
    pth = td / "python312._pth"
    pth.write_text("python312.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n", encoding="utf-8")
    pyembed.enable_site(pth); pyembed.enable_site(pth)
    ls = [x.strip() for x in pth.read_text(encoding="utf-8").splitlines()]
    if ls.count("import site") != 1 or "#import site" in ls or ls.count(r"Lib\site-packages") != 1 or "python312.zip" not in ls:
        fails.append(f"._pth 改写不对：{ls}")
    wh = td / "wheelhouse"; wh.mkdir()
    (wh / "requirements.txt").write_text("numpy==2.2.6\nscipy==1.15.3  # x\n", encoding="utf-8")
    pyembed.write_manifest(wh, "3.12", "win_amd64", wh / "requirements.txt")
    mj = json.loads((wh / "manifest.json").read_text(encoding="utf-8"))
    if mj.get("python_version") != "3.12" or mj.get("platform") != "win_amd64" or mj.get("packages") != {"numpy": "2.2.6", "scipy": "1.15.3"}:
        fails.append(f"manifest.json 不对：{mj}")
    # 版本不符：manifest 写一个本机不可能的版本
    (wh / "manifest.json").write_text(json.dumps({"python_version": "2.7", "platform": "win_amd64"}), encoding="utf-8")
    for tool in ("plantmodel.py", "randplant.py"):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "doctor"], capture_output=True, text=True,
                           env={"DZ_WHEELHOUSE": str(wh), "PATH": "/usr/bin:/bin"})
        d = json.loads(r.stdout)
        bp = str(td / "python" / "python.exe")
        if (r.returncode != 1 or d["ok"] or d["reason"] != "python_mismatch" or "不匹配" not in d["message_zh"]
                or "2.7" not in d["message_zh"] or "python\\python.exe" not in d["message_zh"]
                or not d["install_cmd"].startswith(f'"{bp}"') or "--no-index" not in d["install_cmd"]
                or "Traceback" in r.stdout + r.stderr or "pip" in r.stderr):
            fails.append(f"{tool} 版本不符路径不对：{r.stdout!r} {r.stderr!r}")
    # 平台不符
    (wh / "manifest.json").write_text(json.dumps({"python_version": f"{sys.version_info[0]}.{sys.version_info[1]}", "platform": "dz_no_platform"}), encoding="utf-8")
    d = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "plantmodel.py"), "doctor"], capture_output=True, text=True,
                                  env={"DZ_WHEELHOUSE": str(wh), "PATH": "/usr/bin:/bin"}).stdout)
    if d["ok"] or d["reason"] != "python_mismatch" or "平台" not in d["message_zh"]:
        fails.append(f"平台不符路径不对：{d}")
    # 相符 + 自带解释器存在 → 优先它
    (wh / "manifest.json").write_text(json.dumps({"python_version": f"{sys.version_info[0]}.{sys.version_info[1]}", "platform": pydeps.platform_tag()}), encoding="utf-8")
    (td / "python").mkdir(); (td / "python" / "python.exe").write_bytes(b"")
    d = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "plantmodel.py"), "doctor"], capture_output=True, text=True,
                                  env={"DZ_WHEELHOUSE": str(wh), "PATH": "/usr/bin:/bin"}).stdout)
    if not d["ok"] or d["python"] != str(td / "python" / "python.exe") or not d["install_cmd"].startswith(f'"{td / "python" / "python.exe"}"'):
        fails.append(f"相符时应 ok 且优先自带解释器：{d}")
# 导入冒烟：伪造一个装了但导入就炸的 numpy
with tempfile.TemporaryDirectory() as td:
    (pathlib.Path(td) / "numpy").mkdir()
    (pathlib.Path(td) / "numpy" / "__init__.py").write_text("raise ImportError('DLL load failed')\n")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "plantmodel.py"), "doctor"], capture_output=True, text=True,
                       env={"DZ_WHEELHOUSE": "/opt/wh", "PATH": "/usr/bin:/bin", "PYTHONPATH": td})
    d = json.loads(r.stdout)
    if d["ok"] or d["reason"] != "import_failed" or "numpy" not in d["import_errors"] or "导入失败" not in d["message_zh"] or r.returncode != 1:
        fails.append(f"导入冒烟没报出坏的 numpy：{d}")
for f in fails:
    print("✗ [pydeps]", f)
if not fails:
    print("✓ 离线依赖：清单含 5 个钉版本包，自带嵌入版 Python + ._pth + manifest，doctor 版本/平台不符给 python_mismatch 中文说明，缺包中文提示")
sys.exit(1 if fails else 0)
