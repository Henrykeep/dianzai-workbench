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
pk = (ROOT / "tools" / "package_windows.sh").read_text(encoding="utf-8") + (ROOT / "tools" / "stage_pyembed.sh").read_text(encoding="utf-8")
for s in ("tools/wheelhouse.txt", "pip download", "--no-index --find-links"):
    if s not in pk:
        fails.append(f"package_windows.sh 缺 {s!r}")
for wf in ("ci.yml", "app-windows.yml"):
    if "tools/wheelhouse.txt" not in (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8"):
        fails.append(f"{wf} 没装 tools/wheelhouse.txt")
import tempfile  # noqa: E402
_WH = tempfile.mkdtemp(prefix="dzwh")
for tool in ("plantmodel.py", "randplant.py"):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "doctor"], capture_output=True, text=True,
                       env={"DZ_WHEELHOUSE": _WH, "PATH": "/usr/bin:/bin"})
    d = json.loads(r.stdout)
    if not {"ok", "missing", "install_cmd", "reason", "message_zh", "python"} <= set(d) or r.returncode != (0 if d["ok"] else 1):
        fails.append(f"{tool} doctor 格式/退出码不对：{r.stdout!r} rc={r.returncode}")
    if "--no-index" not in d["install_cmd"] or _WH not in d["install_cmd"] or "http" in d["install_cmd"]:
        fails.append(f"{tool} install_cmd 不是离线命令：{d['install_cmd']}")
    if not d["ok"]:
        fails.append(f"本机缺依赖 {d['missing']}（测试环境应装齐 tools/wheelhouse.txt）")
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pydeps; pydeps.require('dz_no_such_pkg')",
                    str(ROOT / "tools")], capture_output=True, text=True, env={"DZ_WHEELHOUSE": _WH, "PATH": "/usr/bin:/bin"})
if r.returncode == 0 or "缺少 Python 依赖" not in r.stderr or "--no-index" not in r.stderr or "Traceback" in r.stderr:
    fails.append(f"缺包提示不对：{r.stderr!r}")
# 自带嵌入版 Python：打包脚本钉版本 + sha256、走 fetch_url、改 ._pth、写 manifest、装进自带解释器
for s in ("python-$PYVER-embed-amd64.zip", "PYEMBED_SHA=", "fetch_url \"$PYEMBED_URL\"", "pyembed.py\" pth",
          "pyembed.py\" manifest", "--target \"$STAGE/python/Lib/site-packages\"", "tools\\pydeps.py\" repair"):
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
    (td / "python").mkdir(); (td / "python" / "python.exe").write_bytes(b"")
    (wh / "_pip").mkdir(); (wh / "_pip" / "pip-25.0.1-py3-none-any.whl").write_bytes(b"")
    # 版本不符（Windows 安装包布局）：manifest 写一个本机不可能的版本
    (wh / "manifest.json").write_text(json.dumps({"python_version": "2.7", "platform": "win_amd64"}), encoding="utf-8")
    for tool in ("plantmodel.py", "randplant.py"):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "doctor"], capture_output=True, text=True,
                           env={"DZ_WHEELHOUSE": str(wh), "PATH": "/usr/bin:/bin", "DZ_DOCTOR_OS": "win32"})
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
    d = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "plantmodel.py"), "doctor"], capture_output=True, text=True,
                                  env={"DZ_WHEELHOUSE": str(wh), "PATH": "/usr/bin:/bin"}).stdout)
    if not d["ok"] or d["python"] != str(td / "python" / "python.exe") or not d["install_cmd"].startswith(f'"{td / "python" / "python.exe"}"'):
        fails.append(f"相符时应 ok 且优先自带解释器：{d}")
# 导入冒烟：伪造一个装了但导入就炸的 numpy
with tempfile.TemporaryDirectory() as td:
    (pathlib.Path(td) / "numpy").mkdir()
    (pathlib.Path(td) / "numpy" / "__init__.py").write_text("raise ImportError('DLL load failed')\n")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "plantmodel.py"), "doctor"], capture_output=True, text=True,
                       env={"DZ_WHEELHOUSE": _WH, "PATH": "/usr/bin:/bin", "PYTHONPATH": td})
    d = json.loads(r.stdout)
    if d["ok"] or d["reason"] != "import_failed" or "numpy" not in d["import_errors"] or "导入失败" not in d["message_zh"] or r.returncode != 1:
        fails.append(f"导入冒烟没报出坏的 numpy：{d}")
# #137：wheelhouse 不存在 → 绝不给指向不存在路径的命令
env0 = {"DZ_WHEELHOUSE": "/nonexistent/dz-wh", "PATH": "/usr/bin:/bin"}
d = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "pydeps.py"), "doctor"], capture_output=True, text=True, env=env0).stdout)
if d["install_cmd"] is not None or not d["ok"]:
    fails.append(f"wheelhouse 不存在、包都在：应 ok 且 install_cmd=null：{d}")
sys.path.insert(0, str(ROOT / "tools"))
import importlib.util as _iu  # noqa: E402
_orig = _iu.find_spec
for osk, want, bad in (("win32", "重新运行安装程序", ".venv"), ("linux", "python3.12 -m venv .venv", "python.exe"),
                       ("darwin", "brew install python@3.12", "python.exe")):
    os_env = dict(env0, DZ_DOCTOR_OS=osk)
    code = ("import sys,json,importlib.util as u; sys.path.insert(0,sys.argv[1]); import pydeps; o=u.find_spec;"
            "u.find_spec=lambda n,*a: None if n=='numpy' else o(n,*a); print(json.dumps(pydeps.doctor(),ensure_ascii=False))")
    d = json.loads(subprocess.run([sys.executable, "-c", code, str(ROOT / "tools")], capture_output=True, text=True, env=os_env).stdout)
    if (d["ok"] or d["reason"] != "wheelhouse_missing" or d["install_cmd"] is not None or want not in d["message_zh"]
            or bad in d["message_zh"] or "numpy" not in d["missing"]):
        fails.append(f"[{osk}] wheelhouse_missing 不对：{d}")
    if osk != "win32" and "pydeps.py wheelhouse --platform" not in d["message_zh"]:
        fails.append(f"[{osk}] 没给断网办法：{d['message_zh']}")
# Linux/macOS 源码运行 + Windows 离线包 → python_mismatch，不提 python.exe，给 venv / wheelhouse 办法
with tempfile.TemporaryDirectory() as td:
    wh = pathlib.Path(td) / "wheelhouse"; wh.mkdir()
    (wh / "manifest.json").write_text(json.dumps({"python_version": "3.12", "platform": "win_amd64"}), encoding="utf-8")
    for osk, plat in (("linux", "linux"), ("darwin", "macos")):
        d = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "pydeps.py"), "doctor"], capture_output=True, text=True,
                                      env={"DZ_WHEELHOUSE": str(wh), "PATH": "/usr/bin:/bin", "DZ_DOCTOR_OS": osk}).stdout)
        m = d["message_zh"]
        if (d["reason"] != "python_mismatch" or d["install_cmd"] is not None or "python.exe" in m or "venv" not in m
                or f"--platform {plat}" not in m or "不匹配" not in m):
            fails.append(f"[{osk}] python_mismatch 说明不对：{d}")
# repair：pip 英文报错 → 中文
import pydeps  # noqa: E402,F811
for out, reason in (("ERROR: Could not find a version that satisfies the requirement numpy==2.2.6\nERROR: No matching distribution found for numpy==2.2.6", "python_mismatch"),
                    ("ERROR: Could not open requirements file: [Errno 2] No such file or directory: '/workspace/wheelhouse/requirements.txt'", "wheelhouse_missing"),
                    ("ERROR: something odd", "pip_failed")):
    e = pydeps.explain_pip(out, 1)
    if e["reason"] != reason or e["ok"] or "No matching" in e["message_zh"] or "Errno" in e["message_zh"] and reason != "pip_failed":
        fails.append(f"explain_pip({reason}) 不对：{e}")
if not pydeps.explain_pip("", 0)["ok"]:
    fails.append("explain_pip 成功时应 ok")
r = subprocess.run([sys.executable, str(ROOT / "tools" / "pydeps.py"), "repair"], capture_output=True, text=True,
                   env={"DZ_WHEELHOUSE": "/nonexistent/dz-wh", "PATH": "/usr/bin:/bin"})
if "Traceback" in r.stderr or "Errno" in r.stdout + r.stderr:
    fails.append(f"repair 不应甩英文报错：{r.stdout!r} {r.stderr!r}")
# 嵌入版 Python 没 tkinter：latency flash 给中文说明，不甩 Traceback
r = subprocess.run([sys.executable, "-c", "import sys; sys.modules['tkinter']=None; sys.path.insert(0, sys.argv[1]);"
                    "from dzlink import latency; latency.cmd_flash(None, None)", str(ROOT / "host" / "python")], capture_output=True, text=True)
if r.returncode == 0 or "Traceback" in r.stderr or "tkinter" not in r.stderr or "办法" not in r.stderr:
    fails.append(f"latency flash 缺 tkinter 提示不对：{r.stderr!r}")
# wheelhouse 子命令的 pip 参数：只要 wheel、cp312、可重复 --platform、预设展开
av = pydeps.wheelhouse_argv(["macos", "linux", "macosx_11_0_arm64"], "3.12", pathlib.Path("/o"), pathlib.Path("/o/r.txt"))
plats = [av[i + 1] for i, x in enumerate(av) if x == "--platform"]
if (plats != ["macosx_11_0_arm64", "macosx_10_9_x86_64", "manylinux2014_x86_64"] or "--only-binary=:all:" not in av
        or av[av.index("--python-version") + 1] != "3.12" or av[av.index("--implementation") + 1] != "cp" or av[2:4] != ["pip", "download"]):
    fails.append(f"wheelhouse pip 参数不对：{av}")
if pydeps.expand_platforms(["linux"]) != ["manylinux2014_x86_64"]:
    fails.append("linux 预设不对")
for f in fails:
    print("✗ [pydeps]", f)
if not fails:
    print("✓ 离线依赖：清单含 5 个钉版本包，自带嵌入版 Python + ._pth + manifest，doctor 版本/平台不符给 python_mismatch 中文说明，缺包中文提示")
sys.exit(1 if fails else 0)
