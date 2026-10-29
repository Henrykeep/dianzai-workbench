---
name: dz-firmware
description: 在 dianzai-workbench 里换板、换引脚、加电赛题目或子系统、改控制周期时先读。给 5 个决策、两条最短路径和文件级改法纪律。
---
# dz-firmware：换板 / 加题的最短路径

只写不显然的东西。细节按需读链接（入口短、细节在 docs，学的是灵眸 skill 的渐进披露）。

## 先做 5 个决定（30 秒）
| 决定 | 选项 | 怎么选 |
|---|---|---|
| 芯片走哪条路 | STM32 → `stm32-cubemx`（唯一主线）；MSPM0 → `mspm0-driverlib`；PC 仿真 → `host-sim` | STM32 新板一律走 CubeMX |
| 引脚从哪来 | CubeMX `.ioc` 的 User Label / SysConfig `.syscfg` | 标签名 = 逻辑资源名（`PWM_MOTOR_A`、`ENC_MOTOR_A_A`…），见 `docs/05-CubeMX工作流.md` |
| 子系统周期 | `project.yaml` 的 `period_ms` | 视觉 5、底盘/球杆 10 是常用起点；dt 自动同源 |
| 上位机链路 | LINK 串口（dzframe）还是 RTT | 无多余串口时用 RTT（`firmware/proto/dzrtt`） |
| 裸机还是 FreeRTOS | 板卡 yaml 的 `rtos:` | 子系统多于 3 个、或有阻塞外设时用 FreeRTOS |

## 换板（只改引脚）
1. 复制最像的板目录 `boards/<旧板>` → `boards/<新板>`。
2. CubeMX 打开 `.ioc`，改引脚、保留 User Label，**GENERATE CODE**。
3. `python3 tools/ioc_import.py boards/<新板>/cubemx/*.ioc -o boards/<新板>/board.yaml`（参数见 `docs/05-CubeMX工作流.md`）。
4. `make check`（含 `check_gen_consistency.py`：漏了 GENERATE 会报残留引脚）。
5. `make BOARD=<新板> APP=port_selftest`，上板看 LED / LINK 回显。

## 加一道题
1. 复制 `examples/2026H_ball` 的 `project.yaml` 结构（状态、参数、测试项）。
2. 每个子系统 `python3 tools/new_subsys.py examples/<题> <名> --owns .. --reads .. --period ..`。
3. 子系统只读写共享状态；硬件只在 `io/`。
4. 先 `make BOARD=host-sim APP=<题>` 在工作台上调通，再上板。
5. 急停、链路看门狗由 `firmware/framework/coord` 和 `dzctl_wd_*` 提供，不要自己再写一套。
6. `make check` + `make -C examples/<题>/tests`。

## 坑（踩过的）
- 手写频率宏和实际调用频率不一致 → 速度错 3 倍（用户 p1 工程，docs/27 §4.2 ⑨）。周期只写在 `period_ms`。
- 改了 `.ioc` 没 GENERATE：编译照过，上电旧引脚还在被驱动。
- 链接脚本 FLASH 写系列最大值是有意的，容量靠 `__flash_kb` ASSERT 卡（`docs/notes/implemented/2026-10-29-flash-assert.md`）。
- MSPM0 的 DriverLib 函数名 AI 常编造，先查 `docs/20-MSPM0速查.md`。

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
