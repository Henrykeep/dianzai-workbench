---
triggers: k230, canmv, cv_lite, 钢球, kmodel, yolo, 01studio
---
# K230 视觉（本仓库现成脚本）
- 现成脚本（上游原样 + `DZ_FRAME` 补丁，经 `host/k230/dzsend.py` 发 dzframe）：
  - `third_party/vendored/k230_edc_skill/k230_2026_steel_ball_kalman_224.py`：单类 YOLO 钢球，224×224 输入，二维匀速 Kalman + 半径平滑，短暂漏检外推 → 通道 2 `ball`（flags bit0 有效 bit1 预测, x_px, y_px, r_px）。kmodel 不在仓库，要用户自己的；只有 320 模型时把 MODEL_INPUT_SIZE 和 RGB888P_SIZE 一起改成 320。
  - `k230_25e_original/optimized/dual_frame_high_fps.py`：2025E 激光/目标点 → 通道 1 `target`。
  - `third_party/vendored/k230_mspm0g_contest/k230_rect_track.py`、`k230_servo_track_v2.py`：矩形追踪→云台角 → 通道 3 `gimbal`（pan/tilt ×10）。rect/shape/triangle_detect、sensor_diag 没有串口输出。
- 主控端解码：`python3 tools/gen_coproc.py boards/k230-vision/board.yaml -o <dir> --prefix k230`。改字段要两边一起改，`make check` 的 test_k230_vision 会查。
- 多通道：显示/RTSP 一路，识别一路低分辨率；屏幕默认只显示左上角 FPS，框和十字线做成调试开关。
- 先查固件自带例程和 cv_lite 示例再写 API，不要凭空编函数名。没有在 K230 实机上验证过这些脚本，先让用户报 AI FPS 和串口字节。
