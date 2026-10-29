# mechanical/calc —— 转动惯量 / 扭矩 / 电机选型估算

`mech.py`（纯 Python，只需 PyYAML）：读一个机构 yaml（模板在 `../templates/`），算所需扭矩、转速、功率，按电机机械特性和安全系数核对，并给出 host-sim 能用的 `sim:` 参数块。

```bash
python3 mechanical/calc/mech.py mechanical/templates/diff_chassis.yaml
python3 mechanical/calc/mech.py mechanical/templates/ball_plate.yaml --sim /tmp/sim.yaml
python3 mechanical/calc/test_mech.py      # 7 个手算算例（make check 会跑）
```

| 通用函数 | 公式 |
|---|---|
| `inertia(shape, m, …)` | 圆柱 ½mr²、圆环 mr²、细杆 mL²/12、板 m(a²+t²)/12、长方体 m(a²+b²)/12、球 0.4mr²，`d=` 平行轴 +md² |
| `axis_torque` | T = Jα + 重力矩 + 摩擦 |
| `bang_bang_alpha` | 用时 t 摆 θ（先加速后减速）：α = 4θ/t² |
| `motor_check` | 线性机械特性 T(n) = T_stall(1 − n/n0)；`ok` = 可用扭矩 ≥ 安全系数 × 需求且未超空载转速；有 `rated_torque_nm` 再核连续工况；有减速比和转子惯量时给惯量比 J_load/(N²J_rotor)（经验 ≤10 好调） |

机构（`kind`）：`diff_chassis`（F = m(a + g sinθ + Crr g cosθ)，每轮 Fr/n + 轮子惯量，除效率）、`gimbal`（每轴 Jα + 质心偏移重力矩）、`beam` / `ball_plate`（梁/板 + 球在最远处，连杆比 `lever_ratio`）。

**局限（如实）**：线性电机特性、刚体、忽略弹性和间隙；电机数值要用手册或实测（模板里的是示例）。结果是选型估算，最终以台架实测为准；`struct_version` 变了按 `../README.md` 约定重新标定。
