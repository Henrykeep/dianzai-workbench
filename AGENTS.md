# AGENTS.md —— 给改这个仓库的 AI（含 dzbench 内置 Agent）

只写不显然的规则和坑。细节以 `docs/` 为准；芯片事实以**数据手册 / 参考手册 / SDK 头文件**为准，本文与它们冲突时听它们的。

## 硬规则
- STM32：CubeMX 生成 + HAL，**不写寄存器**（确需时加 `DZ-REG-OK` 注释并说明理由，见 `docs/05-CubeMX工作流.md`）。
- MSPM0：SysConfig + DriverLib（`docs/10-SysConfig工作流.md`）。
- 换板只改引脚：板级差异只进 `boards/<板>/board.yaml`，应用代码不出现引脚号。
- 分层依赖由 `tools/check_deps.py` 强制（`docs/02-分层与依赖.md`）；改公开接口要同步 `iface.lock.json`（`make check` 会报）。
- 没在真实硬件上跑过的，写明 **[未测]**（CHANGELOG 的四级标注见文件头）。
- 一个逻辑改动一个提交；提交前 `make check` 和 `make test` 都要绿。

## 常用命令
- `make check`：全部静态检查与自检（不需要硬件、不需要交叉编译器以外的东西）。
- `make test`：桌面工作台侧车测试（离线）。
- `make BOARD=host-sim APP=car_2wd`：编出 PC 仿真板，dzbench 的 `sim:car_2wd` 就用它。

## 坑
- `apps/*/app.yaml` 的 `link:` 改了，板子心跳里的 schema 哈希就变，工作台需要新的 `build/**/link_schema.json`。
- 参数 `default:` 只是上电值；现场调好的值用工作台“写回 yaml”，别手抄。
- 急停（DATA 0x7F）和命令（0x7E）的 id 是保留的，应用自定义 DATA 不能用。
- 第三方代码只进 `third_party/`（不入库，`tools/fetch_third_party.sh` 拉取），移植按 `docs/04-入库检查清单.md`。

## 地图
- `firmware/` 可移植模块；`ports/` 各芯片移植层；`boards/` 板级 yaml；`apps/`、`examples/` 应用。
- `tools/` 生成器与检查器；`host/` PC/视觉端；`app/` 桌面工作台（docs/17、docs/18）。
- 索引：`docs/README.md`；机器可读入口：`llms.txt`。
