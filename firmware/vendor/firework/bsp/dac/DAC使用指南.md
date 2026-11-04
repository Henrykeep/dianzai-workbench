# BSP DAC 使用指南

## 1. 硬件配置

| 逻辑通道 | 外设 | 引脚 | 原始范围 | 标称参考电压 |
| --- | --- | --- | --- | --- |
| `BSP_DAC_CHANNEL_OUTPUT_0` | DAC0 OUT | PA15 | 0～4095 | 3300 mV |

PA15 是模拟输出引脚。使用时应确认该引脚没有同时连接到其他推挽输出。
当前器件/SysConfig 不能通过单纯修改 IOMUX 把这路 12 位 DAC 改到 PA22。
若项目必须释放 PA15，需改用外部 DAC、DDS 或 PWM + 低通滤波方案。

## 2. 公开接口

```c
BSPDACInstance *BSPDACRegister(BSP_DAC_Channel_e channel);
bool BSPDACWriteRaw(BSPDACInstance *instance, uint16_t raw_value);
bool BSPDACStartWaveform(BSPDACInstance *instance,
    const uint16_t *samples, uint16_t sample_count,
    BSP_DAC_Sample_Rate_e sample_rate);
bool BSPDACStopWaveform(BSPDACInstance *instance);
bool BSPDACSetEnabled(BSPDACInstance *instance, bool enabled);
bool BSPDACIsEnabled(const BSPDACInstance *instance);
uint16_t BSPDACGetRawValue(const BSPDACInstance *instance);
uint16_t BSPDACGetMaximumRawValue(const BSPDACInstance *instance);
uint16_t BSPDACGetReferenceMillivolts(const BSPDACInstance *instance);
```

## 3. 基本使用

```c
static BSPDACInstance *dac_output;

void DACExampleInit(void)
{
    dac_output = BSPDACRegister(BSP_DAC_CHANNEL_OUTPUT_0);
    if (dac_output == NULL) {
        return;
    }

    (void)BSPDACWriteRaw(dac_output, 2048U);
    (void)BSPDACSetEnabled(dac_output, true);
}
```

`2048` 约为 12 位满量程的一半，对应的理想输出电压约为：

```text
2048 ÷ 4095 × 3300 mV ≈ 1650 mV
```

实际输出会受参考电压、负载和芯片误差影响。

## 4. 注册、写值和使能的区别

- `BSPDACRegister()`：获得实例并把保存的初始原始值设为 0。
- `BSPDACWriteRaw()`：保存并写入一个 0～4095 的原始值。
- `BSPDACSetEnabled(true)`：启用 DAC，并恢复最近一次成功写入的值。
- `BSPDACSetEnabled(false)`：关闭模拟输出，但保留最近一次写入值。

推荐先写入安全初值，再启用输出，避免启动瞬间出现非预期电压。

## 5. Timer + DMA查找表输出

BSP 提供 DAC 硬件 Sample Timer、FIFO 和 DMA_CH0 的循环输出机制，但不负责生成
正弦、三角等波形。上层把已经生成好的12位查找表和硬件采样率传入：

```c
static const uint16_t square_table[] = {
    500U, 500U, 3000U, 3000U
};

(void)BSPDACStartWaveform(dac_output, square_table,
    sizeof(square_table) / sizeof(square_table[0]),
    BSP_DAC_SAMPLE_RATE_4_KHZ);
```

该示例实际输出1kHz方波。DMA使用全通道重复单次传输，由硬件自动恢复源地址和
传输长度并持续循环。连续DDS使用一个2048点双半区表，DMA半程事件和DAC完成事件
分别通知上层回填空闲的1024点半区，块边界不需要CPU重装DMA。调用
`BSPDACStopWaveform()`、写固定值或关闭DAC都会停止Sample Timer、DMA和FIFO。

支持的采样率为500/1k/2k/4k/8k/16k/100k/200k/500k/1MSPS。实际业务应使用
`modules/dac/dac_output`，由它自动选择采样率、表长和周期数。

## 6. 并发与层次注意事项

- BSP 不提供 FreeRTOS 互斥锁。
- 多任务写同一个 DAC 时会互相覆盖输出值。
- BSP 使用原始数值，不负责毫伏到原始值的换算。
- 应用层优先使用 `application/waveform/waveform_output`，由它通过 `modules/dac` 统一控制使能、波形和参数。

## 7. 与 ADC 回环测试

可以将 PA15 通过串联电阻连接到 ADC 输入，例如 PA27，再观察采样波形：

```text
PA15(DAC) ── 100 Ω ── PA27(ADC/COMP)
GND       ─────────── GND
```

使用外部回环信号前将 LaunchPad `J17 OFF`，避免板载光电二极管影响
PA27。

不要把 DAC 输出接到另一个推挽数字输出。未连接的 ADC 引脚处于悬空状态，可能因串扰显示出幅度较小的相似波形。
