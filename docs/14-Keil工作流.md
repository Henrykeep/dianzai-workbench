# 14 Keil MDK 工作流（主力 IDE）

> 用户两个工程都是 Keil MDK V5.32、Arm Compiler 6（uAC6=1）。**【未验证】本机没有 Keil，下面的注入结果只验证了 XML 结构与幂等性，没有在 µVision 里打开或编译过。**

## 编译器要求
- 模块代码是严格 C99（`make compat` 用 `gcc -std=c99 -pedantic-errors` 检查，无 GNU 扩展），属性/打包/对齐只能用 `firmware/common/dz_compiler.h` 的宏（AC6、AC5、tiarmclang、IAR、GCC 各有分支）。
- AC6：默认设置即可（Language C: c99 或 gnu99 都行）。
- AC5（旧工程）：Options → C/C++ → 勾选 **C99 Mode**（即 `--c99`）。【未验证】

## 把模块加进已有 Keil 工程
1. 生成板卡表：`make BOARD=<板> APP=<应用> gen` → `build/<板>/gen/board_gen.{h,c}`。
2. 注入（可重复运行，只增删 `dz/` 开头的组，原文件备份为 `.bak`）：
```sh
python3 tools/keil_inject.py <工程>/MDK-ARM/xxx.uvprojx \
  --module firmware/algo/pid --module firmware/drivers/motor_dc --module firmware/drivers/encoder \
  --module firmware/proto/dzframe --module ports/stm32-cubemx \
  --extra-src build/<板>/gen/board_gen.c --extra-inc build/<板>/gen --extra-inc apps/include \
  --extra-src apps/<应用>/app_main.c
```
   TIM 时基工程再加 `--define DZ_CM_TIM_TIMEBASE`，FreeRTOS 工程加 `--define DZ_CM_RTOS_FREERTOS`（与 board_gen.mk 的 BOARD_DEFS 一致）。
3. 在 CubeMX 生成的 main.c 的 USER CODE 区放接缝（docs/05）。
4. **回调冲突**：ports/stm32-cubemx 定义了 `HAL_UART_RxCpltCallback`、`HAL_UART_ErrorCallback`、（SysTick 时基时）`HAL_TIM_PeriodElapsedCallback`。原工程里同名回调要删掉或改成转发，否则链接报重复定义。
5. 以后修改模块列表，重新运行同一条命令即可。

## 测试
`make check` 会跑 `tools/test_keil_inject.py`：对 `tools/testdata/real/` 下两个真实 .uvprojx 的副本注入两次，检查 XML 合法、第二次无变化、原有组都在。
