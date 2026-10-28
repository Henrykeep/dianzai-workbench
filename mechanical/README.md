# mechanical/ —— 机械结构板块（第 0 阶段：目录与约定预留，尚无模型与工具实现）

> 来源：2026 H 题的教训 —— 机械结构（架构）与 3D 建模和电控同等重要。
> **建模软件：SolidWorks**（用户确认）。每个零件存 `.SLDPRT` 源文件 + `.STEP`（通用交换）+ `.STL`（3D 打印）+ Bambu Studio `.3mf` 打印工程（拓竹打印机），附参数说明与打印参数说明。装配体存 `.SLDASM`。

| 目录 | 放什么 | 状态 |
|---|---|---|
| `constraints/` | 每道题一个 `<题号>.yaml`：题目尺寸/重量/结构限制，转成可逐条勾选的检查清单 | 预留 |
| `calc/` | 重心、转动惯量、扭矩/电机选型估算脚本（Python，输入 = 零件参数表） | 预留 |
| `models/<零件名>/` | 可复用参数化零件：`<名>.SLDPRT` + `<名>.STEP` + `<名>.STL` + `<名>.3mf`（Bambu Studio）+ `PARAMS.md`（含打印参数）+ `VERSION` | 预留 |
| `assemblies/<项目>/` | 整机装配 `.SLDASM`（+ 导出 STEP）、引用 models 的版本、`STRUCT_VERSION`、标定绑定表 | 预留 |

## 约定（与固件模块同一套“三件套”思想，见 docs/09-机械结构.md）
1. **每个零件 = .SLDPRT + .STEP + .STL + .3mf + PARAMS.md + VERSION**。SLDPRT 是唯一可编辑源（参数用 SolidWorks“全局变量/方程式”驱动，PARAMS.md 中的名字与全局变量名一致）；STEP/STL 由 SLDPRT 导出，.3mf 由该 STL 在 Bambu Studio 中切片设置后保存，都是派生产物，改了源必须重新导出（入库检查比对三者修改时间）；PARAMS.md 的“打印参数”表写明打印机型号、材料、喷嘴、层高、墙数、填充率/图案、支撑（类型/位置）、打印方向，必须与 .3mf 内设置一致；PARAMS.md 写每个驱动参数的含义、单位、取值范围、关联的电控参数（如轮径 → counts_per_rev/mm_per_count）。
2. **结构版本**：`assemblies/<项目>/STRUCT_VERSION` 采用 MAJOR.MINOR.PATCH；改变质量分布/传动比/安装位置 = MINOR 以上，必须重新标定。
3. **标定与参数绑定**：`assemblies/<项目>/calib.yaml` 记录“结构版本 → project.yaml params 的值”（如 mm_per_px、舵机零位、PID 增益）。固件启动/工作台连接时比对结构版本，不一致即告警（第 1 阶段实现）。
4. `*.SLDPRT *.SLDASM *.STEP *.STL *.3mf` 用 Git LFS（见 .gitattributes）；SolidWorks 临时文件 `~$*` 已在 .gitignore；不要提交导出的网格缓存。
