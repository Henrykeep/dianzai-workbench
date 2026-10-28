/**
 * @file dz_err.h
 * @brief 全工程统一错误码。所有层（pal / algo / drivers / apps）共用。
 *
 * 规则：
 *  - 成功恒为 0（DZ_OK），失败为负数，便于 `if (err) {...}` 与 `if (err < 0)`。
 *  - 新增错误码只能追加，不得改已有数值（会破坏遥测/日志里的历史记录）。
 *  - 本头文件只依赖 C 标准库，属于 common 层。
 */
#ifndef DZ_ERR_H
#define DZ_ERR_H

typedef enum {
    DZ_OK       =  0,  /**< 成功 */
    DZ_EINVAL   = -1,  /**< 参数非法：空指针、越界、NaN、配置自相矛盾 */
    DZ_ENODEV   = -2,  /**< 逻辑 ID 在本板卡上不存在（board.yaml 未定义） */
    DZ_EBUSY    = -3,  /**< 资源忙，例如上一帧 DMA 发送尚未完成 */
    DZ_ENOTSUP  = -4,  /**< 本移植层不支持该功能（不是错误，是能力缺失） */
    DZ_ETIMEOUT = -5,  /**< 超时 */
    DZ_ESTATE   = -6,  /**< 调用顺序错误，例如未 init 就使用 */
    DZ_EIO      = -7,  /**< 底层硬件/驱动返回失败 */
    DZ_EFAIL    = -8   /**< 自检未通过等通用失败 */
} dz_err_t;

/** 返回错误码的短名，用于日志。永不返回 NULL。 */
static inline const char *dz_err_str(dz_err_t e)
{
    switch (e) {
    case DZ_OK:       return "OK";
    case DZ_EINVAL:   return "EINVAL";
    case DZ_ENODEV:   return "ENODEV";
    case DZ_EBUSY:    return "EBUSY";
    case DZ_ENOTSUP:  return "ENOTSUP";
    case DZ_ETIMEOUT: return "ETIMEOUT";
    case DZ_ESTATE:   return "ESTATE";
    case DZ_EIO:      return "EIO";
    case DZ_EFAIL:    return "EFAIL";
    default:          return "E?";
    }
}

#endif /* DZ_ERR_H */
