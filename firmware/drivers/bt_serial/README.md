# bt_serial — HC-05 / JDY-31 串口蓝牙

按行收发 + 非阻塞 AT 配置（改名、改波特率）+ STATE 连接脚。透传时就是一根串口线，可直接配合 dzlink/调参命令用。

## board.yaml
```yaml
uart:
  - { name: BT, instance: USART3, tx: PB10, rx: PB11, baud: 9600 }   # 出厂：HC-05 9600、JDY-31 9600
gpio:
  - { name: BT_STATE, pin: PC0, dir: in }     # 可省
  - { name: BT_EN, pin: PC1, dir: out }       # HC-05 KEY，可省
```

## 用法
```c
bt_init(&bt, &(bt_cfg_t){ RES_UART_BT, RES_GPIO_BT_STATE, RES_GPIO_BT_EN, BT_HC05, 1000 });
char line[64];
if (bt_poll(&bt, pal_millis(), line, sizeof line)) handle_cmd(line);   /* 10 ms 任务 */
/* 一次性改名改波特率（HC-05 需 EN 高上电 + board.yaml 里 BT 设 38400） */
bt_config_start(&bt, "DZ-CAR", 115200, pal_millis());
/* 之后照常 bt_poll，bt_at_state() 变成 DONE / FAIL；FAIL 时 bt_at_current() 是卡住的命令 */
```
- 安全：蓝牙命令里**不要**提供解除急停的指令（工作台规则：自动化不得清急停）；`R` 命令同样会清急停，不要映射到蓝牙。
- 模块 RXD 多为 3.3 V 电平，但部分 HC-05 底板是 5 V，接 MCU 前确认。

## 测试状态
- 【已实测】主机单测：假模块（读 UART TX、按规则回 OK/ERROR），行拼接（一次多行/半行/超长丢弃）、发送、HC-05 与 JDY-31 命令格式、错误与超时、非法名字/波特率、STATE/EN 脚。
- 【未验证】真实模块（AT 命令按常见手册整理，不同固件版本可能有差异）。
