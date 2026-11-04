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
| python-control（control ≥ 0.10） | BSD-3-Clause | The Python Control Systems Library developers（Richard M. Murray 等）；`tools/randplant.py` 用 `control.rss` 生成随机稳定系统、`control.pade` 近似纯滞后、`control.c2d` 离散化；侧车 `app/sidecar/dzbench/tuning/autotune.py` 用于模型仿真与 PID 初值；传递依赖 numpy、scipy（BSD-3-Clause） | https://github.com/python-control/python-control |
| SysIdentPy | BSD-3-Clause | Wilson Rocha Lacerda Junior 等 | https://github.com/wilsonrljr/sysidentpy ；侧车依赖：`autotune.identify()` 用 FROLS 从阶跃录波辨识 ARX 模型 |
| pytest-timeout（≥ 2.3） | MIT | Floris Bruynooghe 等 | https://github.com/pytest-dev/pytest-timeout ；仅测试：每个测试 120 s 上限，超时打印线程栈 |
| FlashDB（d186ba9） | Apache-2.0 | armink（Meco Man 等） | https://github.com/armink/FlashDB ；原样放在 `firmware/vendor/flashdb/`（含 FAL），`firmware/vendor/port_pal/dz_store.c` 把 FAL 设备接到 `pal_nvm_*`：KVDB 掉电保存参数、TSDB 板上事件日志 |
| EasyLogger（806328e） | MIT | armink | https://github.com/armink/EasyLogger ；原样放在 `firmware/vendor/easylogger/`（只把 `inc/elog_cfg.h` 模板挪成 `elog_cfg_template.h`），移植 `firmware/vendor/port_pal/elog_port.c`，WARN 以上写进 FlashDB 事件日志 |
| SKiDL（881a4d0） | MIT | Dave Vandenbout（devbisme） | https://github.com/devbisme/skidl ；原样放在 `third_party/vendored/skidl/`（省略 KiCad 符号库），`tools/power_check.py` 建网表跑 ERC |
| WireViz（5f961ac） | GPL-3.0 | WireViz 作者（Daniel Rojas 等） | https://github.com/wireviz/WireViz ；原样放在 `tools/vendor_gpl/wireviz/`，**只作独立进程调用**（`python -m wireviz.wv_cli`），`tools/gen_wiring.py` 写 YAML、读它出的 SVG/PNG/BOM |
| STM32_open_pin_data（7d1f151） | BSD-3-Clause | STMicroelectronics | https://github.com/STMicroelectronics/STM32_open_pin_data ；不入库，`tools/fetch_third_party.sh stm32pins` 按 sha256 下载；`tools/families/stm32_open.py` 读引脚复用 / Flash / RAM，`tools/alloc.py --mcu` 支持任意 STM32 |
