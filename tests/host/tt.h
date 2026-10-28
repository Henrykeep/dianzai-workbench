/* 极简测试框架：无依赖，失败时打印文件行号。 */
#ifndef TT_H
#define TT_H
#include <stdio.h>
#include <math.h>
extern int tt_fail, tt_pass;
#define CHECK(c) do { if (c) tt_pass++; else { tt_fail++; printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
#define CHECK_NEAR(a, b, tol) do { double a_ = (a), b_ = (b); if (fabs(a_ - b_) <= (tol)) tt_pass++; else { tt_fail++; \
    printf("  FAIL %s:%d: %s=%g, 期望 %g±%g\n", __FILE__, __LINE__, #a, a_, b_, (double)(tol)); } } while (0)
#define TEST(name) static void name(void)
#define RUN(name) do { printf("- %s\n", #name); name(); } while (0)
#endif
