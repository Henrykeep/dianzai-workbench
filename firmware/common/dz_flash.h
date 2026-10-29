/**
 * @file dz_flash.h
 * @brief 掉电存储区描述（纯类型）：framework/persist 用它存取，drivers/nvm_pal 用 pal_nvm_* 填它。
 * 语义：按 unit 擦（擦后全 0xFF），只能写已擦的区域，off/n 按 8 字节对齐。
 */
#ifndef DZ_FLASH_H
#define DZ_FLASH_H
#include <stdint.h>
#include "dz_err.h"
typedef struct {
    dz_err_t (*erase)(void *ctx, uint32_t off, uint32_t n);
    dz_err_t (*write)(void *ctx, uint32_t off, const void *p, uint32_t n);
    dz_err_t (*read)(void *ctx, uint32_t off, void *p, uint32_t n);
    void *ctx;
    uint32_t base, size, unit;     /**< 本存储用的区域 [base, base+size)，unit = 擦除单位 */
} persist_flash_t;
#endif
