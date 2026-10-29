/**
 * @file nvm_pal.h
 * @brief 把板子的掉电存储区（pal_nvm_*）切成两块交给 framework/persist：前 bb_units 个擦除单位给黑匣子冻结区，其余给参数键值区。
 * 板子没有存储区 → DZ_ENOTSUP，应用照常只用 RAM。版本：NVM_PAL_VERSION
 */
#ifndef NVM_PAL_H
#define NVM_PAL_H
#include "dz_flash.h"
#define NVM_PAL_VERSION "1.0.0"
/** bb 可为 NULL（不要黑匣子区，bb_units 忽略）。键值区至少要 2 个擦除单位。 */
dz_err_t nvm_pal_layout(persist_flash_t *kv, persist_flash_t *bb, uint32_t bb_units);
#endif
