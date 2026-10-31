# 署名（Attribution）

以下依赖的许可要求署名（CC-BY-3.0）。它们只是 app/ui 的开发依赖（许可证检查工具 license-checker-rseidelsohn 间接引入），
不进发行包；按规则列在这里即可，不阻断 `make licenses`。新增 CC-BY 依赖时 `tools/check_npm_licenses.sh` 会要求先登记到本文件。

| 包 | 许可 | 作者 / 版权方 | 来源 |
|---|---|---|---|
| spdx-exceptions | CC-BY-3.0 | The Linux Foundation（SPDX 例外列表数据）；Kyle E. Mitchell 打包 | https://github.com/kemitchell/spdx-exceptions.json |
| spdx-ranges | MIT AND CC-BY-3.0 | The Linux Foundation（SPDX 许可范围数据）；Kyle E. Mitchell 打包 | https://github.com/kemitchell/spdx-ranges.js |

| PID_Helper（公开界面形态） | GPL-3.0 | 交互形态借鉴（草稿/生效分离等），未参考或复制其源码；涉及 `app/sidecar/dzbench/snapshots.py`、`app/sidecar/dzbench/agent/experiment.py` | 公开界面；源码未使用 |
| pypinyin（python-pinyin） | MIT | mozillazg（Huang Huang） | https://github.com/mozillazg/python-pinyin ；侧车运行时依赖，`app/sidecar/dzbench/agent/steptools.py` 的 `slug()` 把中文项目名转成拼音目录名 |
