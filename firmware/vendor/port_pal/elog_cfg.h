/* EasyLogger 配置（芯台 pal 移植，替换原仓库 inc/elog_cfg.h 模板，原件保留为 ../easylogger/elog_cfg_template.h）：
 * 单线程裸机/RTOS 通用，不开异步/缓冲输出（那两项要 pthread），行缓冲 128 B。 */
#ifndef _ELOG_CFG_H_
#define _ELOG_CFG_H_
#define ELOG_OUTPUT_ENABLE
#define ELOG_OUTPUT_LVL ELOG_LVL_VERBOSE
#define ELOG_ASSERT_ENABLE
#define ELOG_LINE_BUF_SIZE 128
#define ELOG_LINE_NUM_MAX_LEN 5
#define ELOG_FILTER_TAG_MAX_LEN 16
#define ELOG_FILTER_KW_MAX_LEN 16
#define ELOG_FILTER_TAG_LVL_MAX_NUM 4
#define ELOG_NEWLINE_SIGN "\r\n"
#endif
