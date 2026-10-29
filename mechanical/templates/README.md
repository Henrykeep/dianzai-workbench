# mechanical/templates —— 机构模板

每个 yaml 是一个机构的参数表，`python3 mechanical/calc/mech.py <yaml>` 直接出扭矩/电机核对。复制到 `mechanical/constraints/` 或项目目录后改成自己的称重/手册值。

| 模板 | 机构 | 关键输入 |
|---|---|---|
| `diff_chassis.yaml` | 差速底盘（循迹/跟随小车） | 整车质量、轮径、最高速度/加速度、坡度、滚阻、效率 |
| `gimbal.yaml` | 二轴云台（激光笔/相机） | 每轴负载尺寸或惯量、质心偏移、最高角速度、加速时间 |
| `ball_plate.yaml` | 球杆 / 平板（kind 也可写 `beam`） | 梁/板长度质量、球质量与最远位置、摆角与时间、连杆比 |

倒立摆、跟随车头等更多机构：同一套通用函数，加一个 `kind` 函数（`mech.py` 的 `KINDS`）和一个模板即可。
