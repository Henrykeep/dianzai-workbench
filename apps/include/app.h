/**
 * @file app.h
 * @brief 应用与移植层 main 之间的约定。每个应用实现这两个函数，main() 由移植层提供：
 *        pal_init() -> app_init() -> for(;;) app_loop()
 */
#ifndef APP_H
#define APP_H
#include "dz_err.h"
dz_err_t app_init(void);   /**< 初始化；返回非 DZ_OK 时移植层进入故障指示（LED 快闪/打印） */
void     app_loop(void);   /**< 主循环体，必须非阻塞 */
#endif
