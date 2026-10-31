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
