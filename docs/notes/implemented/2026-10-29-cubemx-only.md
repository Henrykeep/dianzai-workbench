# STM32 只保留 CubeMX 一条主线；stm32f4-hal 冻结

- **决定**：新 STM32 板一律 `port: stm32-cubemx`。`ports/stm32f4-hal` 冻结：只服务 `stm32f407-skystar`、`dji-rm-c`，不加功能、不接新板。
- **为什么**：两条 STM32 路线并存，新人不知道选哪条，AI 修 bug 只修一边（docs/27 G4）。用户写代码用 Keil/CubeMX + HAL（HANDOVER 用户偏好），CubeMX 路线和用户习惯一致，换引脚只在 .ioc 里点。
- **守护**：`tools/boardlib.py` `F4HAL_FROZEN`，第三块板用 stm32f4-hal 时 validate_board 报错（`make check`）。
- **否决过（本次）**：立刻删除 stm32f4-hal。理由：
  1. 两块存量板还没有 CubeMX 版：天空星已有 `stm32f407-skystar-cubemx`，但它缺电机 B（`make BOARD=stm32f407-skystar-cubemx APP=car_2wd` 报 [缺资源] gpio.MOTOR_B_IN1），RM C 型的 HSE 还是 TODO；
  2. CI `make cross` 里 car_2wd / motor_pos / pan_tilt 的 F407 覆盖目前靠 stm32f407-skystar；
  3. 删除要动这些板子的 .ioc，需要用户在 CubeMX 里确认引脚，不能凭猜。
- **迁移剩余**：天空星 .ioc 补电机 B（PWM/IN1/IN2/编码器 B）→ cross 改用 skystar-cubemx → RM C 型做 .ioc（HSE 确认后）→ 删 ports/stm32f4-hal 与 mk/stm32f4.mk。[未测] 全部。
