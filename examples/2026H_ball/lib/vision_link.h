/**
 * @file vision_link.h
 * @brief 协处理器（Jetson Nano）-> 主控 的视觉帧解析。纯 C、逐字节喂入、无动态内存。
 *
 * 帧格式（ASCII，一行一帧）：  $B,<x>,<y>,<found>*<XX>\n
 *   x,y 为整数像素，found 为 0/1，XX 为 '$' 与 '*' 之间所有字节的异或校验（两位十六进制大写）。
 * 例：$B,320,240,1*?? —— 校验错误、超长、字段缺失的帧计入 bad，不输出。
 * Jetson 端发送示例见 docs/07-app-framework.md。
 */
#ifndef VISION_LINK_H
#define VISION_LINK_H
#include <stdint.h>
#include <stdbool.h>

typedef struct { int16_t x, y; bool found; } vision_frame_t;
typedef struct { char buf[40]; uint8_t n; bool in_frame; uint32_t good, bad; } vision_link_t;

void vision_link_init(vision_link_t *v);
/** 喂一个字节；收到完整有效帧时返回 true 并写 *out。 */
bool vision_link_feed(vision_link_t *v, uint8_t byte, vision_frame_t *out);
/** 生成一帧（给测试和 PC 模拟器用），返回长度。buf 至少 32 字节。 */
int  vision_link_format(char *buf, unsigned size, const vision_frame_t *f);
#endif
