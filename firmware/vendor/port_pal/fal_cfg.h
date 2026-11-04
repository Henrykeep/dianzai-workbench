/* FAL 配置（芯台 pal 移植）：唯一的 flash 设备 = pal_nvm（片内末页 / 外部 SPI flash / host-sim 文件），前一半参数、后一半事件日志。
 * 分区表运行时按 pal_nvm_info 生成（FAL_PART_TABLE_FLASH_DEV_NAME 不用；见 dz_store.c）。 */
#ifndef _FAL_CFG_H_
#define _FAL_CFG_H_
#include <stdio.h>
#define FAL_PRINTF(...) ((void)0)
#define FAL_DEBUG 0
#define FAL_PART_HAS_TABLE_CFG
extern struct fal_flash_dev dz_pal_nvm_flash;
#define FAL_FLASH_DEV_TABLE { &dz_pal_nvm_flash, }
#ifndef DZ_STORE_KV_SIZE
#define DZ_STORE_KV_SIZE 4096   /* 参数区（≥ 2 个擦除单位）；板子可 -D 覆盖 */
#endif
#ifndef DZ_STORE_TS_SIZE
#define DZ_STORE_TS_SIZE 4096   /* 事件日志区（≥ 2 个擦除单位，满了循环覆盖最旧） */
#endif
#define FAL_PART_TABLE { \
    {FAL_PART_MAGIC_WORD, "dz_kv", "pal_nvm", 0, DZ_STORE_KV_SIZE, 0}, \
    {FAL_PART_MAGIC_WORD, "dz_ts", "pal_nvm", DZ_STORE_KV_SIZE, DZ_STORE_TS_SIZE, 0}, \
}
#endif
