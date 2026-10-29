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
