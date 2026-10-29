/* 用户 p1 原样：频率宏 300，实际 100 Hz 调用 */
#define CONTROL_FREQUENCY 300
float speed(int d) { return d * CONTROL_FREQUENCY; }
