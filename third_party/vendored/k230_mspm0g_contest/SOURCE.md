# K230 视觉脚本（mspm0g-contest-skill）

Source: github.com/2262727886-stack/mspm0g-contest-skill@cc7b2bd 04_Software/K230/

| 文件 | 用途 | 改动 |
|---|---|---|
| k230_rect_track.py / k230_servo_track_v2.py | 矩形/目标追踪 → 云台角度（原协议 A5 5A cmd pan tilt XOR） | `send_frame` 开头加 dzframe 分支：发通道 3 gimbal |
| k230_rect_detect.py / k230_shape_detect.py / k230_triangle_detect.py | 矩形 / 形状 / 三角形检测（触屏调参面板），无串口输出 | 未改（只加头注释）；要输出时照 rect_track 的补丁加 `_dz.send` |
| k230_sensor_diag.py | 摄像头传感器诊断 | 未改（只加头注释） |

改动只有：文件头两行 Source 注释；打补丁的文件在 import 之后插入 `DZ_FRAME` 开关 + `_dz_tx()`（依赖 host/k230/dzsend.py），`DZ_FRAME = False` 走上游原协议。
许可：MIT（上游 README 声明；LICENSE 文件按标准文本补齐，见同目录）。
