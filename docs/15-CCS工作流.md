# 15 · CCS 工作流（MSPM0 / 天猛星）

> 【未验证】本文和 `boards/mspm0g3507-tianmengxing/ccs/` 下的文件都**没有在 CCS 中导入编译过**，也没用 tiarmclang 编过（box 上只有 arm-none-eabi-gcc）。格式照抄 TI MSPM0 SDK 2.11 的 `empty_LP_MSPM0G3507_nortos_ticlang.projectspec`。第一次导入请按下面步骤走，遇到报错把信息贴回来。

## 文件
| 文件 | 作用 |
|---|---|
| `ccs/tianmengxing.syscfg` | 唯一配置源（引脚/PWM/QEI/定时器/串口），和 `board.yaml` 一致，由 `make check` 比对 |
| `ccs/mspm0g3507-tianmengxing_car_2wd.projectspec` | `tools/gen_ccs_projectspec.py` 生成，勿手改 |
| `syscfg/ti_msp_dl_config.{c,h}` | 仅供 box 上 gcc 交叉编译的手写合成版；CCS 里**不用**，由 SysConfig 现生成 |

## 步骤
1. 安装 CCS 12.x/20.x、MSPM0 SDK 2.11（`COM_TI_MSPM0_SDK_INSTALL_DIR` 由 CCS 自动识别）、SysConfig 1.2x、TI Arm Clang（tiarmclang）。
2. 仓库根目录先跑 `make BOARD=mspm0g3507-tianmengxing APP=car_2wd gen`，生成 `build/.../gen/board_gen.c`（工程链接它）。
3. CCS：File → Import → C/C++ → CCS Projects → 选 `boards/mspm0g3507-tianmengxing/ccs/`，勾选该 projectspec。
   - 工作台源文件是**链接**（改了直接改仓库）；`.syscfg` 是**复制**进工程。在 CCS 里改了 .syscfg，记得拷回仓库并 `make check`。
4. 打开 .syscfg 看有无冲突（红叉）；有就在 GUI 改好，保存，再把改动回写 `board.yaml`（`syscfg_import.py X.syscfg --check board.yaml`）。
5. Build → Debug（XDS110）。

## 编译器
- tiarmclang 是 clang 前端，会定义 `__clang__`/`__ti__`，`firmware/common/dz_compiler.h` 走 GCC/clang 分支（`__attribute__`、`__asm volatile`）。【未验证】未实际用 tiarmclang 编译。
- 工作台代码是 C11 + `-std=c99 -pedantic-errors` 可过的子集（`make compat`），不依赖 GCC 扩展以外的东西。
- 旧 TI armcl（非 clang）不支持，SDK 2.x 也已不推荐。

## 换应用 / 换板
- 换应用：`python3 tools/gen_ccs_projectspec.py --board mspm0g3507-tianmengxing --app <应用>`，再把 `make check` 里的 `--check` 行改成对应应用。
- 换板：只改 `.syscfg` 引脚 + `board.yaml`，源文件列表不变。
