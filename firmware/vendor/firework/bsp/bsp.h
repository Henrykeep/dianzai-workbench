/**
 * @file bsp.h
 * @brief BSP 总初始化、启动前延时、Flash 操作和故障安全关断接口。
 */
#ifndef BSP_H
#define BSP_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief 初始化 SysConfig 为 MSPM0G3507 生成的时钟和外设配置。
 *
 * 这是 BSP 唯一必须调用的初始化入口。应在注册功能模块以及启动
 * FreeRTOS 调度器之前调用。初始化后会立即停止 ADC/COMP/DAC/PWM
 * 的活动功能，使未启用对应应用时也保持安全态。
 *
 * @return 首次初始化和安全态建立成功返回 true；重入或失败返回 false。
 */
bool BSPInit(void);

/** 启动阶段使用的阻塞毫秒延时，不依赖 FreeRTOS 调度器。 */
void BSPDelayMilliseconds(uint32_t milliseconds);

/**
 * @brief 擦除主 Flash 中 address 所在的一个扇区。
 *
 * Flash 忙期间会保存并关闭全局中断，防止 ISR 从正在操作的
 * Flash 取指。调用者必须确保目标地址属于预留的用户数据区。
 */
bool BSPFlashEraseMainSector(uint32_t address);

/**
 * @brief 把两个 32 位字以硬件生成 ECC 的方式写入主 Flash。
 *
 * @param address 64 位对齐的目标地址。
 * @param words   指向两个 32 位源数据，调用期间不会修改。
 */
bool BSPFlashProgramMain64WithECC(
    uint32_t address, const uint32_t words[2]);

/**
 * 不使用 RTOS 锁地停止采样、捕获、DMA、COMP、SPI、AD9833、DAC 和 PWM。
 * 可从 fault、栈溢出和未实现中断上下文重复调用。
 */
void BSPEnterSafeState(void);

#endif
