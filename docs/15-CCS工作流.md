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

## 烧录（不开 CCS）
工作台“烧录”和 `python -m dzbench --flash` 走 pyOCD，MSPM0 要 TI 的 CMSIS 器件包（DFP）：`tools/fetch_third_party.sh m0pack` 下载并校验 sha256 到 `third_party/packs/`，或设 `DZBENCH_PACK=包路径`；`--doctor` 会检查。2026-10-29 实测：pyOCD 0.x 读这个包能列出 mspm0g3507 目标【仿真/离线】；接探针真烧【未测】。

## 走查记录（2026-10-29，box 上按用户步骤走，没有 CCS / tiarmclang / 探针）
| 步骤 | 结果 | 处理 |
|---|---|---|
| 干净克隆后 `make … gen` | ✗ 报“找不到 MSPM0 SDK”退出，`linkgen/link_gen.c` 没生成 → projectspec 里链接的这个文件不存在，导入会缺文件 | 已修：gen / vars 不再要求 SDK（CCS 用户的 SDK 在 CCS 里）。复查：projectspec 里所有 -I 和链接文件都存在 |
| projectspec 只有 car_2wd | 换应用要自己跑生成器 | 文档已写（下面“换应用”）；未改 |
| DFP 下载 | URL 用的是 TI 的 `latest/` 目录 + 固定文件名 1.3.1，TI 发新版后会 404 / 校验失败 | 记录；失败时按提示用 `pyocd pack install mspm0g3507` |
| CCS 导入、SysConfig 打开、tiarmclang 编译、XDS110 下载 | 【未测】box 上装不了 CCS GUI | 第一次导入请把报错贴回来 |

## 编译器
- tiarmclang 是 clang 前端，会定义 `__clang__`/`__ti__`，`firmware/common/dz_compiler.h` 走 GCC/clang 分支（`__attribute__`、`__asm volatile`）。【未验证】未实际用 tiarmclang 编译。
- 工作台代码是 C11 + `-std=c99 -pedantic-errors` 可过的子集（`make compat`），不依赖 GCC 扩展以外的东西。
- 旧 TI armcl（非 clang）不支持，SDK 2.x 也已不推荐。

## 换应用 / 换板
- 换应用：`python3 tools/gen_ccs_projectspec.py --board mspm0g3507-tianmengxing --app <应用>`，再把 `make check` 里的 `--check` 行改成对应应用。
- 换板：只改 `.syscfg` 引脚 + `board.yaml`，源文件列表不变。
