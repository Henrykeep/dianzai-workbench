# <零件名> 参数说明（复制到 models/<零件名>/PARAMS.md）
- 版本：见同目录 VERSION（MAJOR=安装接口变化；MINOR=尺寸参数变化；PATCH=外观/倒角）
- 文件：`<名>.SLDPRT`（源，SolidWorks 版本：TODO）/ `<名>.STEP`（AP214）/ `<名>.STL`（单位 mm）/ `<名>.3mf`（Bambu Studio 版本：TODO）

## 打印参数（必须与 .3mf 内设置一致）
| 项 | 值 |
|---|---|
| 打印机 / 喷嘴 | 拓竹 TODO 型号 / 0.4 mm |
| 材料 | TODO（PLA / PETG / PLA-CF …） |
| 层高 | TODO mm |
| 墙层数 | TODO |
| 填充 | TODO %，图案 TODO |
| 支撑 | TODO（无 / 普通 / 树状；仅构建板 / 全部），位置说明 |
| 打印方向 | TODO（受力方向与层纹的关系） |
| 打印后处理 | TODO（热熔螺母、打磨 …） |

| 全局变量名 | 含义 | 单位 | 默认 | 范围 | 关联电控参数（project.yaml params） |
|---|---|---|---|---|---|
| D_wheel | 轮径 | mm | TODO | | mm_per_count |
| M_part | 质量（称重实测） | g | TODO | | 重心/转动惯量估算 |
