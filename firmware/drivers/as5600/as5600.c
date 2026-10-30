/**
 * @file as5600.c
 * @brief 【已停用 2.0.0，2026-10-31】原实现写作时参照了 GPL-3.0 的 pid_helper 例程 as5600_dev.c，无法排除派生，已整体移除。
 *        这里只保留接口：不访问 I2C，所有函数返回 DZ_ENOTSUP，读数恒为 0。待按 docs/参考来源.md“待净室重写清单”重写。
 */
#include <string.h>
#include "as5600.h"

dz_err_t as5600_init(as5600_t *e, const as5600_cfg_t *cfg)
{
    if (e) { memset(e, 0, sizeof *e); if (cfg) e->cfg = *cfg; }
    return DZ_ENOTSUP;
}
dz_err_t as5600_check_magnet(as5600_t *e, uint8_t *status) { (void)e; if (status) *status = 0u; return DZ_ENOTSUP; }
dz_err_t as5600_update(as5600_t *e, uint32_t now_us) { (void)e; (void)now_us; return DZ_ENOTSUP; }
dz_err_t as5600_set_zero_here(as5600_t *e) { (void)e; return DZ_ENOTSUP; }
dz_err_t as5600_selftest(void) { return DZ_ENOTSUP; }
