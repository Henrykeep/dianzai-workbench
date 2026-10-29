# AGENTS.md —— 给改这个仓库的 AI（含 dzbench 内置 Agent）

只写不显然的规则和坑。细节以 `docs/` 为准；芯片事实以**数据手册 / 参考手册 / SDK 头文件**为准，本文与它们冲突时听它们的。

## 硬规则
- STM32：**只走 `ports/stm32-cubemx`**（`ports/stm32f4-hal` 冻结，只服务两块存量板）；CubeMX 生成 + HAL，**不写寄存器**（确需时加 `DZ-REG-OK` 注释并说明理由，见 `docs/05-CubeMX工作流.md`）。
- MSPM0：SysConfig + DriverLib（`docs/10-SysConfig工作流.md`；坑先看 `docs/20-MSPM0速查.md`）。
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
- 换板/加题先读 `skills/dz-firmware/SKILL.md`；设计取舍与否决过的方案在 `docs/notes/`。
- 索引：`docs/README.md`；机器可读入口：`llms.txt`。

<!-- BEGIN dz-edit-rules -->
## 改法纪律（文件级；唯一来源 `skills/dz-firmware/edit-rules.md`，`python3 tools/check_ai_docs.py --sync` 同步到 AGENTS.md 和 SKILL.md）
| 要做的事 | 只改这里 | 不许碰（会被哪条检查拦） |
|---|---|---|
| 换引脚 | CubeMX 打开 `boards/<板>/cubemx/*.ioc` 改 User Label → GENERATE CODE → `tools/ioc_import.py`；MSPM0 改 `.syscfg` → `tools/syscfg_import.py` | 手改 `cubemx/Core/`、手改 board.yaml 的 `resources:`（`check_gen_consistency.py`、`ioc-check`） |
| 加一块板 | 只新建 `boards/<板>/`，按 `docs/06-新增板卡.md` | `firmware/`、`apps/`、`examples/` 一行都不改 |
| 加题 / 加子系统 | `examples/<题>/`：先 `tools/new_subsys.py` 出骨架，再改 `project.yaml` | 在子系统里 include 硬件头、读别的子系统的私有变量（`check_deps.py`） |
| 改周期 / 频率 | 只改 `project.yaml` 的 `period_ms`，代码用生成的 `PERIOD_MS_*` | 在 subsys/io 里手写 `*_HZ`、`*_FREQ*`、`CONTROL_FREQUENCY`（`check_deps.py` 频率规则） |
| 改参数默认值 | `project.yaml` / `app.yaml` 的 `default:`，或工作台"写回 yaml" | 手改 `gen/`、`build/` 下任何文件（每次构建重生成） |
| 改公开接口 | `firmware/**.h` + `iface.lock.json` + CHANGELOG | 不更新 lock（`iface_hash.py --check`） |
| 改移植层 | `ports/<系列>/` 只实现 `firmware/pal/pal.h` | 在 ports 里写题目逻辑 |
| 第三方代码 | 只放 `third_party/`（不入库） | 把 GPL/AGPL 代码复制进仓库 |

- 改动方式：**精确的小替换**，一次一个逻辑改动；不做正则批量替换、不顺手重排无关代码。
- 新增条件编译：`io_main.c` 这类胶水文件不再加 `#if` 分支，差异放进 board.yaml 或各自的小文件（`docs/notes/` 有理由）。
- 改完必须跑 `make check`；动了固件再跑对应 `make BOARD=... APP=...`；没上板的写 **[未测]**。
<!-- END dz-edit-rules -->
