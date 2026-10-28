/* newlib 系统调用桩：本工程不使用文件/进程，全部返回失败。用于消除链接警告。 */
#include <errno.h>
#include <sys/stat.h>
int _close(int f) { (void)f; return -1; }
int _fstat(int f, struct stat *st) { (void)f; st->st_mode = S_IFCHR; return 0; }
int _getpid(void) { return 1; }
int _isatty(int f) { (void)f; return 1; }
int _kill(int p, int s) { (void)p; (void)s; errno = EINVAL; return -1; }
int _lseek(int f, int p, int d) { (void)f; (void)p; (void)d; return 0; }
int _read(int f, char *b, int n) { (void)f; (void)b; (void)n; return 0; }
int _write(int f, char *b, int n) { (void)f; (void)b; return n; }
