# UART2 波形发送工具使用指南

## 1. 工具说明

`uart2_waveform_sender.py` 是运行在电脑上的 UART2 测试工具，用于生成波形采样值，
通过 USB 转串口模块发送给 MSPM0G3507，并在 TUI 中接收和显示开发板返回的
VOFA+ JustFloat ADC 波形。开发板收到电脑采样后，可以在当前显示菜单（默认 TFT）的
`WAVEFORM → UART2 PB16` 页面显示实时波形，也可以在
`FFT SPECTRUM → FFT UART2` 页面查看频谱和主峰频率。

工具支持以下波形：

- `sine`：正弦波
- `square`：方波
- `triangle`：三角波
- `sawtooth`：锯齿波

每个采样值使用以下四字节帧发送：

```text
0xAA + int16 大端高字节 + int16 大端低字节 + 0x55
```

例如发送采样值 `1000`：

```text
AA 03 E8 55
```

发送采样值 `-1000`：

```text
AA FC 18 55
```

开发板回传使用固件现有的 JustFloat 格式：

```text
float32 小端数据 + 00 00 80 7F
```

TUI 会自动从连续字节流中识别这种帧，并显示最新值、最小值、最大值、接收数量
和最近一段回传波形。当前回传值来自 `APP_ADC_JUSTFLOAT_DEFAULT_SOURCE` 选择的
PA27 或 PB19 ADC，不是对电脑发送帧的原样回显；源值 `1U` 对应 PB19，旧枚举名
仍可能写 `PA21`。

## 2. 硬件连接

需要使用 3.3 V TTL 电平的 USB 转串口模块：

```text
USB-TTL TX  → PB16 / UART2 RX
USB-TTL RX  ← PB15 / UART2 TX
USB-TTL GND → 开发板 GND
```

只向开发板发送波形时，不需要连接 USB-TTL RX。需要在电脑显示开发板返回波形时，
必须同时连接 `PB15 → USB-TTL RX`。禁止将 RS-232 电平或 5 V 串口信号直接连接
PB15/PB16。

CMSIS-DAP 调试器显示出的 `/dev/ttyACM0` 不一定连接到 PB16。若调试器没有提供
对应的 UART2 引脚连接，需要额外使用 USB 转串口模块。

## 3. 安装运行环境

### Linux

进入项目目录：

```bash
cd /home/qianmo/workspace_ccstheia/freertos_firework
```

创建并激活虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装串口依赖：

```bash
python -m pip install -r tools/requirements.txt
```

验证 PySerial：

```bash
python -c "import serial; print(serial.__version__)"
```

以后重新打开终端，只需要重新进入项目目录并激活环境：

```bash
cd /home/qianmo/workspace_ccstheia/freertos_firework
source .venv/bin/activate
```

也可以不激活虚拟环境，直接使用项目解释器：

```bash
.venv/bin/python tools/uart2_waveform_sender.py --list-ports
.venv/bin/python tools/uart2_waveform_sender.py --tui
```

在 Arch Linux 中，终端里的 `python` 可能指向 `/usr/sbin/python`。如果这个系统
Python 没有安装 PySerial，工具会无法扫描串口并显示 `No serial ports found` 或
`pyserial is not installed`。优先使用项目 `.venv`，不要根据系统中是否存在
`/dev/ttyACM*` 来判断当前 Python 一定能扫描到它们。

启动 TUI 前建议先执行：

```bash
source .venv/bin/activate
python -c "import serial; print(serial.__version__)"
python tools/uart2_waveform_sender.py --list-ports
```

如果已经知道设备名，可以直接指定：

```bash
.venv/bin/python tools/uart2_waveform_sender.py \
    --tui \
    --port /dev/ttyUSB0
```

### Windows

在项目目录执行：

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r tools\requirements.txt
```

## 4. 使用 TUI 终端界面

启动界面：

```bash
python tools/uart2_waveform_sender.py --tui
```

也可以在启动时指定优先使用的串口和初始参数：

```bash
python tools/uart2_waveform_sender.py \
    --tui \
    --port /dev/ttyUSB0 \
    --wave sine \
    --frequency 1 \
    --sample-rate 100 \
    --amplitude 1000
```

### 界面字段

| 字段 | 说明 |
| --- | --- |
| `Serial port` | 当前选择的电脑串口设备 |
| `Waveform` | 需要生成的波形类型 |
| `Frequency` | 波形频率，单位 Hz |
| `Sample rate` | 每秒发送的采样数量 |
| `Amplitude` | 波形相对于中心值的峰值 |
| `Offset` | 波形的直流偏移 |
| `Status` | `DISCONNECTED`、`CONNECTED` 或 `SENDING` |
| `Samples` | 本次发送和接收的累计采样数量 |
| `Return` | 最新回传值、当前缓冲区最小值/最大值和数据年龄 |

界面中的 `Returned waveform` 是从 PB15 收到并解析出的 JustFloat 实际数据；
`Generated TX waveform preview` 是电脑准备向 PB16 发送的归一化波形，两者可以
同时显示以便比较。

界面还会显示开发板 UART2 FFT 的点数、频率范围、频率分辨率、预计主峰 bin 和
预计显示主峰频率。这些值是根据当前工程默认的 64 点 FFT 和 100 samples/s
采样率计算出的辅助信息，不是开发板回传的测量结果。

### 操作按键

| 按键 | 功能 |
| --- | --- |
| `↑` / `↓` | 选择需要修改的字段 |
| `←` / `→` | 切换串口、波形或调整参数 |
| `Space` | 开始或停止发送 |
| `O` | 打开或关闭串口，只监听回传时使用 |
| `C` | 清空回传波形、统计和解析缓存 |
| `R` | 重新扫描串口设备 |
| `Q` | 停止发送、关闭串口并退出 |

终端窗口至少需要 68 列 × 27 行。插入 USB 转串口模块后，可以在界面中按 `R`
刷新串口列表。

使用 `--tui --port /dev/ttyUSB0` 启动时会自动打开串口并监听回传；未使用
`--port` 时，在界面选择串口后按 `O` 开始监听。按 `Space` 会在保持接收的同时
启动或停止电脑波形发送。

## 5. 开发板操作步骤

1. 烧录并运行当前工程。
2. 连接 USB-TTL TX、RX、GND 与开发板。
3. 在 `application/app_config.h` 中启用 UART2 和 ADC JustFloat，然后重新编译烧录：

   ```c
   #define APP_ENABLE_UART2         (1U)
   #define APP_ENABLE_ADC_JUSTFLOAT (1U)
   ```

   `APP_ADC_JUSTFLOAT_DEFAULT_SOURCE=0U` 返回 PA27，`1U` 返回 PB19。
4. 需要观察电脑发送波形时，在显示菜单选择 `WAVEFORM → UART2 PB16`；需要观察
   频谱时，选择 `FFT SPECTRUM → FFT UART2`。
5. 在电脑上启动 TUI，选择正确串口并按 `O`，或直接通过 `--port` 自动连接。
6. `Returned waveform` 应开始显示 PA27/PB19 ADC 回传数据。
7. 如需同时测试电脑向开发板发送，按 `Space` 开始发送。
8. 屏幕收满 1024 点后应冻结显示最后 128 点；需要重测时在波形页长按 S1。

建议先使用以下参数测试：

```text
Waveform    : sine
Frequency   : 1.0 Hz
Sample rate : 100 samples/s
Amplitude   : 1000
Offset      : 0
Baud        : 115200
```

使用 UART2 FFT 时，电脑工具的 `Sample rate` 必须与固件中的
`FFT_ANALYSIS_UART2_SAMPLE_RATE_HZ` 一致。当前固件默认值是 100 samples/s，
对应参数为：

```text
FFT point count : 64
Frequency range : 0 Hz ~ 50 Hz
Bin resolution  : 1.5625 Hz
Frame time      : 0.64 s
```

例如发送 10 Hz 正弦波时，最近的频点是 bin 6，屏幕通常会显示约 9.375 Hz。
输入频率没有恰好落在 FFT bin 中心时会产生频谱泄漏，因此相邻频点也可能出现幅值。

## 6. 普通命令行模式

### 查看串口

```bash
python tools/uart2_waveform_sender.py --list-ports
```

Linux 中 USB 转串口通常显示为 `/dev/ttyUSB0` 或 `/dev/ttyACM0`，Windows 中通常
显示为 `COM3`、`COM5` 等。

### 不连接串口预览数据帧

```bash
python tools/uart2_waveform_sender.py \
    --dry-run \
    --wave sine \
    --frequency 1 \
    --sample-rate 100 \
    --preview-count 16
```

### 持续发送正弦波

```bash
python tools/uart2_waveform_sender.py \
    --port /dev/ttyUSB0 \
    --baud 115200 \
    --wave sine \
    --frequency 1 \
    --sample-rate 100 \
    --amplitude 1000 \
    --offset 0
```

按 `Ctrl+C` 停止发送。

### 测试 UART2 FFT

```bash
python tools/uart2_waveform_sender.py \
    --port /dev/ttyUSB0 \
    --baud 115200 \
    --wave sine \
    --frequency 10 \
    --sample-rate 100 \
    --amplitude 1000 \
    --offset 0
```

然后进入显示菜单的 `FFT SPECTRUM → FFT UART2` 页面。工具会在启动时打印开发板
FFT 配置和预计主峰位置，约等待一帧采样时间后屏幕会刷新频谱。

### 定时发送三角波

```bash
python tools/uart2_waveform_sender.py \
    --port /dev/ttyUSB0 \
    --wave triangle \
    --frequency 5 \
    --sample-rate 100 \
    --amplitude 1500 \
    --duration 20
```

上述命令发送 20 秒后自动停止。Windows 用户将 `/dev/ttyUSB0` 改为实际的
`COM` 端口，例如 `COM5`。

## 7. 命令行参数

| 参数 | 说明 | 默认值 |
| --- | --- | ---: |
| `--tui` | 打开发送器和 JustFloat 回传波形监视器 | 关闭 |
| `--port` | 串口设备 | 无 |
| `--baud` | UART 波特率 | `115200` |
| `--wave` | 波形类型 | `sine` |
| `--frequency` | 波形频率，单位 Hz | `1` |
| `--sample-rate` | 每秒发送的采样数量 | `100` |
| `--amplitude` | 波形峰值 | `1000` |
| `--offset` | 直流偏移 | `0` |
| `--duration` | 发送时间；`0` 表示持续发送 | `0` |
| `--dry-run` | 只打印数据帧，不打开串口 | 关闭 |
| `--preview-count` | `--dry-run` 打印的帧数 | `16` |
| `--list-ports` | 显示串口列表并退出 | 关闭 |

采样值必须满足有符号 16 位整数范围：

```text
-32768 ≤ Offset - Amplitude
Offset + Amplitude ≤ 32767
```

为避免混叠，工具要求：

```text
Frequency < Sample rate / 2
```

如果发送采样率不是 100 samples/s，工具仍可用于时域波形显示，但会给出
FFT 采样率不匹配警告。此时固件仍按 100 samples/s 换算频率，屏幕的 FFT 频率
结果会按比例偏移。

## 8. 常见问题

### `bash: py: 未找到命令`

Linux 不使用 Windows 的 `py` 启动命令。请优先激活项目虚拟环境后使用
`python`：

```bash
cd /home/qianmo/workspace_ccstheia/freertos_firework
source .venv/bin/activate
python tools/uart2_waveform_sender.py --tui
```

或者直接使用：

```bash
.venv/bin/python tools/uart2_waveform_sender.py --tui
```

### `file:///...` 无法运行

`file://` 是 IDE 使用的文件链接格式，不是终端文件路径。终端中应执行：

```bash
cd /home/qianmo/workspace_ccstheia/freertos_firework
.venv/bin/python tools/uart2_waveform_sender.py --tui
```

不要直接运行 `tools/__pycache__/` 中的 `.pyc` 缓存文件。

### `pyserial is not installed`

说明当前 Python 环境没有安装 PySerial：

```bash
cd /home/qianmo/workspace_ccstheia/freertos_firework
source .venv/bin/activate
python -m pip install -r tools/requirements.txt
```

### 界面显示 `<no serial port>`

依次检查：

1. 确认正在使用项目虚拟环境，而不是没有 PySerial 的系统 Python：

   ```bash
   which python
   python -c "import serial; print(serial.__version__, serial.__file__)"
   ```

   激活 `.venv` 后，`which python` 应指向项目下的 `.venv/bin/python`。

2. 使用同一个解释器列出串口：

   ```bash
   .venv/bin/python tools/uart2_waveform_sender.py --list-ports
   ```

3. 检查 Linux 设备节点：

   ```bash
   ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
   ls -l /dev/serial/by-id/ 2>/dev/null
   ```

4. USB 转串口模块插入后，在 TUI 中按 `R` 重新扫描。
5. `/dev/ttyUSB0` 通常是独立 USB-TTL；`/dev/ttyACM0`、`ttyACM1` 等通常来自
   CMSIS-DAP/XDS110 调试器，但不保证连接到程序使用的 PB15/PB16 UART2。
6. 如果只看到 CMSIS-DAP/XDS110 端口，却没有任何端口实际连接 PB15/PB16，
   需要增加一个 3.3 V USB-TTL 模块。
7. 也可以使用稳定的 `/dev/serial/by-id/...` 路径作为 `--port`，避免重插设备后
   `ttyACM` 编号变化。

### 串口存在但打开失败

先确认串口没有被其他串口工具占用。Linux 如果提示 `Permission denied`，检查设备
权限和当前用户所属的串口设备组，然后重新登录使用户组变更生效。

Arch Linux 可以使用以下命令检查占用程序：

```bash
fuser /dev/ttyACM0
fuser /dev/ttyUSB0
```

如果输出进程号，再查看具体程序：

```bash
ps -p 进程号 -o pid=,comm=,args=
```

VOFA+、串口助手和 Python 工具不能同时打开同一个串口。例如 VOFA+ 已占用
`/dev/ttyACM1` 时，应先在 VOFA+ 中断开串口或退出程序，然后再启动本工具。

权限问题可以检查：

```bash
ls -l /dev/ttyUSB0
id
```

Arch Linux 串口设备通常属于 `uucp` 组。如设备权限不是所有用户可读写，可将当前
用户加入 `uucp` 后重新登录：

```bash
sudo usermod -aG uucp "$USER"
```

不要用 `sudo python ...` 作为长期解决方案，因为它会切换 Python 环境，并可能
再次找不到项目 `.venv` 中安装的 PySerial。

### 已发送但屏幕没有波形

依次确认：

1. 显示菜单数据源已经选择 `UART2 PB16`。
2. USB-TTL TX 确实连接 PB16，而不是 PB15。
3. USB-TTL 与开发板已经共地。
4. USB-TTL 使用 3.3 V TTL 电平。
5. 电脑和开发板 UART2 波特率均为 `115200`。
6. TUI 状态已经变为 `SENDING`，`Sent` 数量持续增加。
7. 当前页面正在收集新帧；重新进入页面或长按 S1 可开始下一次 1024 点收集。

### TUI 没有回传波形

依次确认：

1. `PB15 / UART2 TX` 已连接 USB-TTL 的 `RX`。
2. USB-TTL 与开发板已经共地，并使用 3.3 V TTL 电平。
3. `APP_ENABLE_UART2=1U` 和 `APP_ENABLE_ADC_JUSTFLOAT=1U`，并已重新编译烧录。
4. PA27 或 PB19 对应输入已由编译配置启用。
5. TUI 状态为 `CONNECTED` 或 `SENDING`，不是 `DISCONNECTED`。
6. USB-TTL 支持全双工，且串口没有被 VOFA+ 或其他工具占用。
7. JustFloat 回传格式为 `float32 LE + 00 00 80 7F`；普通文本日志不会被画成波形。

### 屏幕没有 UART2 FFT 或频率不正确

依次确认：

1. `application/app_config.h` 中已经启用 `APP_ENABLE_UART2=1U` 和
   `APP_ENABLE_WAVEFORM_MEASUREMENT=1U`，并重新编译、烧录。
2. 当前显示已进入 `FFT SPECTRUM → FFT UART2`，而不是 ADC 的 FFT 页面。
3. 工具的 `Sample rate` 是 100 samples/s，与
   `FFT_ANALYSIS_UART2_SAMPLE_RATE_HZ` 一致。
4. 已连续接收到至少 64 个有效采样；100 samples/s 时一帧约需 0.64 秒。
5. 输入频率低于 50 Hz，并且最好靠近 1.5625 Hz 的整数倍，以减少频谱泄漏。

### 终端内容显示不完整

将终端窗口调整到至少 68 列 × 27 行，然后重新启动 TUI。
