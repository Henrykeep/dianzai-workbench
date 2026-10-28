/**
 * @file dz_compiler.h
 * @brief 编译器抽象：模块里需要属性/打包/对齐/静态断言时只用这里的宏，不直接写 __attribute__ / __packed / #pragma。
 *
 * 支持（按预定义宏识别）：
 *  - Arm Compiler 6（Keil MDK 默认，armclang）：__ARMCC_VERSION >= 6000000
 *  - Arm Compiler 5（armcc，旧 Keil 工程）：__CC_ARM
 *  - TI Arm Clang（CCS，tiarmclang）：__ti__（同时定义 __clang__）
 *  - IAR：__ICCARM__
 *  - GCC / Clang（arm-none-eabi-gcc、主机测试）
 * 【已实测】仅 GCC（arm-none-eabi-gcc 13.3 与主机 gcc，含 -std=c99 -pedantic-errors 检查，见 `make compat`）。
 * 【未验证】AC6 / AC5 / tiarmclang / IAR：本机没有这些编译器，分支按各自手册写成。
 *
 * 用法：
 *   DZ_PACKED_BEGIN
 *   typedef struct DZ_PACKED_ATTR { uint8_t a; uint16_t b; } DZ_PACKED_TAIL foo_t;
 *   DZ_PACKED_END
 * 推荐：协议字段一律用 dzframe_put_xx/get_xx 逐字节读写，根本不需要打包结构体。
 */
#ifndef DZ_COMPILER_H
#define DZ_COMPILER_H

#if defined(__CC_ARM)                                   /* Arm Compiler 5 */
#  define DZ_WEAK            __weak
#  define DZ_UNUSED_FN       __attribute__((unused))
#  define DZ_ALIGNED(n)      __align(n)
#  define DZ_NORETURN        __declspec(noreturn)
#  define DZ_INLINE          static __inline
#  define DZ_PACKED_BEGIN
#  define DZ_PACKED_ATTR
#  define DZ_PACKED_TAIL
#  define DZ_PACKED_END
#  define DZ_PACKED_KW       __packed
#elif defined(__ICCARM__)                               /* IAR */
#  define DZ_WEAK            __weak
#  define DZ_UNUSED_FN
#  define DZ_ALIGNED(n)      _Pragma("data_alignment=" #n)
#  define DZ_NORETURN        __noreturn
#  define DZ_INLINE          static inline
#  define DZ_PACKED_BEGIN    _Pragma("pack(push, 1)")
#  define DZ_PACKED_ATTR
#  define DZ_PACKED_TAIL
#  define DZ_PACKED_END      _Pragma("pack(pop)")
#  define DZ_PACKED_KW
#elif defined(__GNUC__) || defined(__clang__)           /* GCC、Clang、AC6（armclang）、tiarmclang */
#  define DZ_WEAK            __attribute__((weak))
#  define DZ_UNUSED_FN       __attribute__((unused))
#  define DZ_ALIGNED(n)      __attribute__((aligned(n)))
#  define DZ_NORETURN        __attribute__((noreturn))
#  define DZ_INLINE          static inline
#  define DZ_PACKED_BEGIN
#  define DZ_PACKED_ATTR     __attribute__((packed))
#  define DZ_PACKED_TAIL
#  define DZ_PACKED_END
#  define DZ_PACKED_KW
#else
#  error "dz_compiler.h：未知编译器，请补充一个分支"
#endif

/** 编译期断言（C99 可用，不依赖 _Static_assert） */
#define DZ_STATIC_ASSERT(cond, tag) typedef char dz_static_assert_##tag[(cond) ? 1 : -1]

#define DZ_ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))

#endif /* DZ_COMPILER_H */
