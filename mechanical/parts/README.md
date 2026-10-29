# mechanical/parts —— CadQuery 参数化零件库（可选）

```bash
pip install cadquery                                    # 可选依赖；没装时脚本和测试都打印“跳过”并成功退出
python3 mechanical/parts/parts.py --list                # 零件与默认参数
python3 mechanical/parts/parts.py motor_mount -o out/ --set motor_d=25 --set screw_pcd=17
python3 mechanical/parts/parts.py all -o out/           # 每个零件出 .step（SolidWorks）+ .stl（Bambu Studio）+ .params.txt
```

| 零件 | 用途 | 主要参数（mm） |
|---|---|---|
| `motor_mount` | L 形电机座：竖板贴减速箱法兰（中心凸台孔 + 圆周螺丝孔），底板长条孔固定到车板 | motor_d、boss_d、screw_pcd、screw_n、wall、base_len |
| `encoder_bracket` | 编码器板支架：过轴孔 + PCB 孔 + 固定孔 | w、h、t、shaft_hole_d、pcb_hole_dx |
| `sensor_bracket` | 灰度/红外板 L 支架，竖板长条孔调离地高度 | pcb_w、drop、slot_len、base_hole_dx |

- 默认值是常见件的**示例**，装前用卡尺量了再 `--set`。电机座：电机从 +Y 侧（底板那侧）装入，轴从竖板孔穿出接轮。
- STEP/STL 是派生产物，不入库；改参数重新导出。要精修：STEP 导入 SolidWorks 另存 .SLDPRT，走 `../README.md` 的主线约定。
- 测试 `test_parts.py`：编码器板体积与手算（3378.15 mm³）一致、包围盒随参数变、STEP 导出再读回体积一致。CI 没装 CadQuery，只在本机装了时真跑。
- 打印参数（材料/层高/填充/方向）按 `../models/PARAMS_TEMPLATE.md` 记在你的项目里。
