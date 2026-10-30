# K230 视觉脚本（Electronics-Design-Competition-Skill）

Source: github.com/Loclove/Electronics-Design-Competition-Skill@cd46b72 assets/k230/

| 文件 | 上游 | 用途 | 改动 |
|---|---|---|---|
| k230_2026_steel_ball_kalman_224.py | assets/k230/k230-2026-steel-ball-kalman-224.py（注明改编自 YaoYanbo 的 K230 高速钢球检测） | YOLO11 224×224 钢球 + 匀速 Kalman | 加 dzframe 补丁：每帧 `ball_tracker.update` 后发通道 2 ball |
| k230_25e_original.py / k230_25e_optimized.py / k230_25e_dual_frame_high_fps.py | assets/k230/k230-25e-*.py | 2025E 激光/目标点（原版 / 优化 / 双帧高帧率） | `send_target` 开头加 dzframe 分支：发通道 1 target |

共同改动：文件名 `-` 改 `_`；文件头加两行 Source 注释；import 之后插入一段 `DZ_FRAME` 开关 + `_dz_tx()`（依赖 host/k230/dzsend.py）。
`DZ_FRAME = False` 时完全走上游原协议（55 AA … 校验）。其余代码逐字未改。
许可：上游未声明，见同目录 LICENSE（仅私有仓库自用，公开前须取得许可）。
