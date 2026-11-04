/* FlashDB 配置（芯台 pal 移植）：KVDB 存参数、TSDB 存事件日志，走 FAL → pal_nvm_*。写粒度 64 bit = pal_nvm 8 字节对齐。 */
#ifndef _FDB_CFG_H_
#define _FDB_CFG_H_
#define FDB_USING_KVDB
#define FDB_USING_TSDB
#define FDB_USING_FAL_MODE
#define FDB_WRITE_GRAN 64
#define FDB_USING_READ_CACHE 0
#define FDB_READ_CACHE_WINDOW 0
#ifndef FDB_PRINT
#define FDB_PRINT(...)
#endif
#endif
