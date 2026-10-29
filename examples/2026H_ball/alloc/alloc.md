# 资源分配结果

| 类型 | 逻辑名 | 来自 | 结果 |
|---|---|---|---|
| gpio | SENSOR1 | ir_gray_array | 分配：pin=PE0, dir=in, pull=up |
| gpio | SENSOR2 | ir_gray_array | 分配：pin=PE1, dir=in, pull=up |
| gpio | SENSOR3 | ir_gray_array | 分配：pin=PE2, dir=in, pull=up |
| gpio | SENSOR4 | ir_gray_array | 分配：pin=PE3, dir=in, pull=up |
| gpio | SENSOR5 | ir_gray_array | 分配：pin=PE4, dir=in, pull=up |
| gpio | SENSOR6 | ir_gray_array | 分配：pin=PE5, dir=in, pull=up |
| gpio | SENSOR7 | ir_gray_array | 分配：pin=PE6, dir=in, pull=up |
| gpio | SENSOR8 | ir_gray_array | 分配：pin=PE7, dir=in, pull=up |
| encoder | MOTOR_A | encoder_ab | 分配：timer=TIM3, pin_a=PA6, pin_b=PA7 |
| encoder | MOTOR_B | encoder_ab | 分配：timer=TIM4, pin_a=PB6, pin_b=PB7 |
| pwm | MOTOR_A | dc_motor_hbridge | 分配：timer=TIM1, channel=1, pin=PA8, freq_hz=20000 |
| pwm | MOTOR_B | dc_motor_hbridge | 分配：timer=TIM1, channel=2, pin=PA9, freq_hz=20000 |
| gpio | MOTOR_A_IN1 | dc_motor_hbridge | 分配：pin=PE8, dir=out |
| gpio | MOTOR_A_IN2 | dc_motor_hbridge | 分配：pin=PE9, dir=out |
| gpio | MOTOR_B_IN1 | dc_motor_hbridge | 分配：pin=PE10, dir=out |
| gpio | MOTOR_B_IN2 | dc_motor_hbridge | 分配：pin=PE11, dir=out |
| uart | VISION | maixcam2 | 分配：instance=USART2, tx=PA2, rx=PA3, baud=115200 |
| uart | BEAM | qd4310 | 分配：instance=USART3, tx=PB10, rx=PB11, baud=921600 |
| gpio | KEY1 | key_gpio | 分配：pin=PE12, dir=in, pull=up |
| i2c | OLED | oled_ssd1306 | 分配：instance=I2C1, scl=PB8, sda=PB9, speed_hz=400000 |
| uart | LINK | 调试链路（工作台） | 分配：instance=UART4, tx=PA0, rx=PA1, baud=115200 |

校验（boardlib.check_board，与 validate_board 相同）：错误 0 / 警告 0 / TODO 2
