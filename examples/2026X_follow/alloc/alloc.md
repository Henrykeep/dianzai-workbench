# 资源分配结果

| 类型 | 逻辑名 | 来自 | 结果 |
|---|---|---|---|
| gpio | LINE0 | ir_gray_array | 分配：pin=PA12, dir=in, pull=up |
| gpio | LINE1 | ir_gray_array | 分配：pin=PB12, dir=in, pull=up |
| gpio | LINE2 | ir_gray_array | 分配：pin=PB13, dir=in, pull=up |
| gpio | LINE3 | ir_gray_array | 分配：pin=PB14, dir=in, pull=up |
| gpio | LINE4 | ir_gray_array | 分配：pin=PB15, dir=in, pull=up |
| gpio | LINE5 | ir_gray_array | 分配：pin=PA0, dir=in, pull=up |
| gpio | LINE6 | ir_gray_array | 分配：pin=PA1, dir=in, pull=up |
| gpio | LINE7 | ir_gray_array | 分配：pin=PA4, dir=in, pull=up |
| encoder | MOTOR_A | encoder_ab | 分配：timer=TIM3, pin_a=PA6, pin_b=PA7 |
| encoder | MOTOR_B | encoder_ab | 分配：timer=TIM4, pin_a=PB6, pin_b=PB7 |
| pwm | MOTOR_A | dc_motor_hbridge | 分配：timer=TIM1, channel=1, pin=PA8, freq_hz=20000 |
| pwm | MOTOR_B | dc_motor_hbridge | 分配：timer=TIM1, channel=2, pin=PA9, freq_hz=20000 |
| gpio | MOTOR_A_IN1 | dc_motor_hbridge | 分配：pin=PA5, dir=out |
| gpio | MOTOR_A_IN2 | dc_motor_hbridge | 分配：pin=PA10, dir=out |
| gpio | MOTOR_B_IN1 | dc_motor_hbridge | 分配：pin=PA11, dir=out |
| gpio | MOTOR_B_IN2 | dc_motor_hbridge | 分配：pin=PB0, dir=out |
| uart | PEER | lora_uart | 分配：instance=USART2, tx=PA2, rx=PA3, baud=115200 |
| gpio | KEY1 | key_gpio | 分配：pin=PB1, dir=in, pull=up |
| i2c | OLED | oled_ssd1306 | 分配：instance=I2C1, scl=PB8, sda=PB9, speed_hz=400000 |
| uart | LINK | 调试链路（工作台） | 分配：instance=USART3, tx=PB10, rx=PB11, baud=115200 |
| timer | CTRL | 应用 requires（控制周期） | 分配：instance=TIM2 |

校验（boardlib.check_board，与 validate_board 相同）：错误 0 / 警告 0 / TODO 1
