# 署名（Attribution）

以下依赖的许可要求署名（CC-BY-3.0）。它们只是 app/ui 的开发依赖（许可证检查工具 license-checker-rseidelsohn 间接引入），
不进发行包；按规则列在这里即可，不阻断 `make licenses`。新增 CC-BY 依赖时 `tools/check_npm_licenses.sh` 会要求先登记到本文件。

| 包 | 许可 | 作者 / 版权方 | 来源 |
|---|---|---|---|
| spdx-exceptions | CC-BY-3.0 | The Linux Foundation（SPDX 例外列表数据）；Kyle E. Mitchell 打包 | https://github.com/kemitchell/spdx-exceptions.json |
| spdx-ranges | MIT AND CC-BY-3.0 | The Linux Foundation（SPDX 许可范围数据）；Kyle E. Mitchell 打包 | https://github.com/kemitchell/spdx-ranges.js |

| PID_Helper（公开界面形态） | GPL-3.0 | 交互形态借鉴（草稿/生效分离等），未参考或复制其源码；涉及 `app/sidecar/dzbench/snapshots.py`、`app/sidecar/dzbench/agent/experiment.py` | 公开界面；源码未使用 |
| pypinyin（python-pinyin） | MIT | mozillazg（Huang Huang） | https://github.com/mozillazg/python-pinyin ；侧车运行时依赖，`app/sidecar/dzbench/agent/steptools.py` 的 `slug()` 把中文项目名转成拼音目录名 |
| Radix Colors（色值） | MIT | WorkOS（Radix）；只抄录 blue11 #0D74CE、red11 #CE2C31 等色值进 `app/ui/src/tokens.css`，未引入依赖 | https://github.com/radix-ui/colors |
| Inter（界面字体，拉丁子集 woff2） | OFL-1.1 | The Inter Project Authors（rsms）；取自 @fontsource-variable/inter 5.3.0 的 `inter-latin-wght-normal.woff2`，放在 `app/ui/src/fonts/`，许可见 `LICENSE-Inter.txt` | https://github.com/rsms/inter |
| Web Awesome（@awesome.me/webawesome 3.14.0） | MIT | Fonticons, Inc.（原 Shoelace）；界面按钮 / 滑条 / 标签 / 卡片 / 骨架组件，本地打包进 `app/ui`，主题由 `app/ui/src/wa-theme.css` 从 tokens 映射；默认图标库已改为空（不访问 Font Awesome CDN）；传递依赖 lit（BSD-3-Clause）、@floating-ui（MIT）等均为宽松许可 | https://github.com/shoelace-style/webawesome |
| python-control | BSD-3-Clause | python-control developers | https://github.com/python-control/python-control ；侧车依赖：`app/sidecar/dzbench/tuning/autotune.py` 模型仿真与 PID 初值，`tools/randplant_standin.py` 与 `tools/randplant.py` 随机对象（rss / pade / c2d） |
| SysIdentPy | BSD-3-Clause | Wilson Rocha Lacerda Junior 等 | https://github.com/wilsonrljr/sysidentpy ；侧车依赖：`autotune.identify()` 用 FROLS 从阶跃录波辨识 ARX 模型 |
