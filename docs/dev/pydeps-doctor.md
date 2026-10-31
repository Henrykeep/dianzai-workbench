# 离线依赖自检（#112）

仿真建模工具（tools/plantmodel.py、tools/randplant.py）依赖 python-control、scipy、numpy、sysidentpy、uncertainties。
清单钉版本在 `tools/wheelhouse.txt`；Windows 安装包把它们打成 `<安装目录>/wheelhouse/`（tools/package_windows.sh），**安装时只从本地装，不联网**。

## 首次启动自检（给侧车）

```
python3 tools/plantmodel.py doctor      # randplant.py doctor 同样可用
{"ok": false, "missing": ["uncertainties"], "install_cmd": "\"C:\\...\\python.exe\" -m pip install --no-index --find-links \"C:\\...\\wheelhouse\" -r \"C:\\...\\wheelhouse\\requirements.txt\""}
```

- 一行 JSON：`ok`（bool）、`missing`（缺的包名列表）、`install_cmd`（离线安装命令字符串）。
- 退出码：齐全 0，缺包 1。
- wheelhouse 路径：环境变量 `DZ_WHEELHOUSE` 优先，否则 `<仓库上一级>/wheelhouse`（安装包布局），再否则仓库内 `wheelhouse/`。
- 缺包时直接跑 plantmodel/randplant 其他子命令：stderr 给中文说明 + 同一条离线命令，退出码 1，不打 Traceback。

## 安装包自带的嵌入版 Python（fw-pyembed）

Windows 包（`tools/package_windows.sh`）带官方 CPython **3.12.10** embeddable zip（python.org，sha256 钉死，走 `tools/fetch_lib.sh` 的 `fetch_url` 重试），布局：

```
<安装目录>/python/python.exe        自带解释器；python312._pth 已打开 site（import site + Lib\site-packages）
<安装目录>/python/Lib/site-packages 打包时已离线装好 tools/wheelhouse.txt 全部依赖
<安装目录>/wheelhouse/              离线 wheel + requirements.txt + manifest.json + _pip/pip-*.whl
<安装目录>/repo/                    工程仓库
<安装目录>/安装离线依赖.bat          补救：用自带解释器 + _pip 里的 pip wheel 离线重装
```

`wheelhouse/manifest.json`：`{"python_version": "3.12", "platform": "win_amd64", "implementation": "cp", "packages": {...}, "bundled_python": "python/python.exe", "pip_wheel": "_pip/pip-….whl"}`。

**后端（侧车）请这样用：** 跑 `tools/*.py` 子进程时，优先 `<安装目录>/python/python.exe`（= `pydeps.bundled_python()`，即 `wheelhouse` 的同级 `python/python.exe`）；不存在时再退回当前解释器。doctor JSON 里的 `python` 字段就是推荐解释器，直接用它即可。

doctor 输出：`{ok, reason, message_zh, missing, python, install_cmd}`。
- `reason: "python_mismatch"`：当前解释器的 主.次 版本或平台标签（`sysconfig.get_platform()`，如 `win_amd64`）与 manifest 不符；不跑 pip，`message_zh` 如「本机 Python 3.11 与离线包 3.12 不匹配，请使用安装目录自带的 python\python.exe（…）」，`install_cmd` 用自带解释器。
- `reason: "import_failed"`：五个包都在但真导入失败（子进程冒烟），`import_errors: {包名: 错误}`，中文 `message_zh`。
- `reason: "missing"`：缺包，`missing` 列包名；`reason: null` 且 `ok: true`：一切正常。
- 没有 manifest.json（开发环境）时不做版本核对。
