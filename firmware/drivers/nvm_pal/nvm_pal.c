/* pal_nvm_* → persist_flash_t，见 nvm_pal.h。 */
#include "nvm_pal.h"
#include "pal.h"

static dz_err_t e(void *c, uint32_t off, uint32_t n) { (void)c; return pal_nvm_erase(off, n); }
static dz_err_t w(void *c, uint32_t off, const void *p, uint32_t n) { (void)c; return pal_nvm_write(off, p, n); }
static dz_err_t r(void *c, uint32_t off, void *p, uint32_t n) { (void)c; return pal_nvm_read(off, p, n); }

dz_err_t nvm_pal_layout(persist_flash_t *kv, persist_flash_t *bb, uint32_t bb_units)
{
    uint32_t size = 0, unit = 0, bb_size;
    dz_err_t rc;
    if (!kv) return DZ_EINVAL;
    if ((rc = pal_nvm_info(&size, &unit)) != DZ_OK) return rc;
    if (!unit || size < unit * 2u) return DZ_ENOTSUP;
    bb_size = bb ? bb_units * unit : 0u;
    if (size < bb_size + unit * 2u) return DZ_EINVAL;
    if (bb) { bb->erase = e; bb->write = w; bb->read = r; bb->ctx = 0; bb->base = 0; bb->size = bb_size; bb->unit = unit; }
    kv->erase = e; kv->write = w; kv->read = r; kv->ctx = 0; kv->base = bb_size; kv->size = size - bb_size; kv->unit = unit;
    return DZ_OK;
}
