---
triggers: k230, canmv, cv_lite, 钢球, kmodel, yolo, 01studio
---
# K230 视觉（本仓库现成脚本）
- 现成脚本（上游原样 + `DZ_FRAME` 补丁，经 `host/k230/dzsend.py` 发 dzframe）：
  - （原 k230_edc_skill 钢球 Kalman 脚本因上游无许可证已删除，待重写）
  - `k230_25e_original/optimized/dual_frame_high_fps.py`：2025E 激光/目标点 → 通道 1 `target`。
  - `third_party/vendored/k230_mspm0g_contest/k230_rect_track.py`、`k230_servo_track_v2.py`：矩形追踪→云台角 → 通道 3 `gimbal`（pan/tilt ×10）。rect/shape/triangle_detect、sensor_diag 没有串口输出。
- 主控端解码：`python3 tools/gen_coproc.py boards/k230-vision/board.yaml -o <dir> --prefix k230`。改字段要两边一起改，`make check` 的 test_k230_vision 会查。
- 多通道：显示/RTSP 一路，识别一路低分辨率；屏幕默认只显示左上角 FPS，框和十字线做成调试开关。
- 先查固件自带例程和 cv_lite 示例再写 API，不要凭空编函数名。没有在 K230 实机上验证过这些脚本，先让用户报 AI FPS 和串口字节。
