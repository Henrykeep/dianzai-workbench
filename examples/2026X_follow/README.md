# 2026X_follow —— 第二道参考例题：D 题式双车循线跟车

> 自拟练习题（不是官方原文），用来把“双车 / 车机通信 + 跟车 + 安全中止”这一类题按 9 步走一遍。换真题时从第 1 步重来。

| 步骤 | 文件 | 命令 |
|---|---|---|
| 1 读题 | `requirements.yaml` | `python3 tools/req.py check examples/2026X_follow/requirements.yaml` |
| 2 选型 | `scheme.yaml` | `python3 tools/scheme.py examples/2026X_follow/requirements.yaml --scheme examples/2026X_follow/scheme.yaml -o out/` |
| 3 分配 | `alloc/`（board.yaml 草稿 + cubemx.md + alloc.md） | `python3 tools/alloc.py examples/2026X_follow/scheme.yaml -o examples/2026X_follow/alloc --app examples/2026X_follow/app.yaml --name follow-car-f103` |
| 4–7 代码 | `app.yaml`、`app_main.c` | `make BOARD=host-sim APP=2026X_follow` |
| 8 回归 | `app/sidecar/tests/test_follow_car.py` | `cd app/sidecar && python3 -m pytest -q tests/test_follow_car.py` |

## 结构
- 同一份固件，参数 `role`：0 前车（循线巡航 + 广播），1 后车（循线 + 跟车）。两车用同一张板、同一套参数表。
- 复用模块：`algo/line_obs`（丢线确认 / 找线 / 超时）、`algo/follow`（间距控制）、`proto/peerlink`（STATE / ABORT 帧，新鲜度 / 乱序检查）。
- 间距 = `gap0_m` + 前车里程增量 − 本车里程。发车前量好两车间距填 `gap0_m`；中途要重新对齐按 `Z`。

## 安全（回归测试逐条断言）
| 场景 | 后车行为 | 仿真结果 |
|---|---|---|
| 前车 2 m/s² 急刹 | follow 减速停，真间距 > gap_min | 最小 ≈ 0.35 m |
| 链路断（> stale_ms 没帧） | LINK_LOST → 按 f_decel 减速到 0；恢复后继续跟 | ≤0.6 s 判出，1.5 s 内停 |
| 前车 ABORT | 立停并锁存，`C` 人工解除 | 锁存 |
| 本车急停 | 先停再连发 3 帧 ABORT，前车也停 | 双向中止 |
| 间距 < gap_min | 立停（TOO_CLOSE） | — |

“没撞车”用仿真侧真间距判（`DZ_SIM_TRUTH` 文件），不信固件自己的估计。仿真没有轮胎打滑和真实无线丢包突发，结论都是 [仿真]，上车要重测。

## 上车前
- `alloc/board.yaml` 是草稿：CubeMX 配完用 `tools/ioc_import.py` 导出覆盖，再复制成 `boards/<你的板>/board.yaml`。
- LoRa 模块配成透传、两车同信道；20 ms 一帧要求空速 ≥19.2 kbps（模块手册核对）。半双工模块两车同时发会碰撞，必要时把一车的发送相位错开 10 ms。
- 编码器 COUNTS_PER_REV、`wheel_circ_m` 实测标定（10 圈法，docs/12）。
