# wit_imu — 维特 WIT 串口姿态模块（JY61P / JY901 / HWT101）

模块内部解算，MCU 只解 11 字节帧：加速度 0x51、角速度 0x52、角度 0x53、磁场 0x54。偏航清零是非阻塞小状态机（解锁 → 清零 → 保存）。

## board.yaml
```yaml
uart:
  - { name: IMU, instance: USART2, tx: PA2, rx: PA3, baud: 115200 }   # JY61P 出厂 9600，HWT101 出厂 9600，用上位机改到 115200
```

## 用法
```c
wit_init(&imu, &(wit_cfg_t){ RES_UART_IMU, WIT_JY61P, 100, 100 });
wit_poll(&imu, pal_millis());                    /* 1~5 ms 任务 */
if (wit_fresh(&imu, pal_millis())) yaw = wit_data(&imu)->yaw;  /* 失联时别拿旧角度闭环 */
wit_zero_yaw_start(&imu, pal_millis());          /* 静止时；JY61P/HWT101 有效，JY901 九轴有磁力计时偏航是绝对角 */
```

## 测试状态
- 【仿真】主机单测：多帧混发、半帧拼接、校验错重同步、噪声字节、比例换算、新鲜度、JY/HWT101 两种清零命令序列与间隔。
- 【未测】真实模块（协议按维特手册和参考工程整理）。
- 参考：ti-contest `wit_jyxx.c`、DS-land-and-air `wit_c_sdk.c` / `bsp_gyro_wit.c`（见 docs/参考来源.md）。
