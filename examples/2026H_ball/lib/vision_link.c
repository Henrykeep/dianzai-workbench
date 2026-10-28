#include <stdio.h>
#include "vision_link.h"

void vision_link_init(vision_link_t *v) { v->n = 0; v->in_frame = false; v->good = v->bad = 0; }

static int hexv(char c) { return c >= '0' && c <= '9' ? c - '0' : (c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1); }

static bool parse_int(const char **p, long lo, long hi, long *out)
{
    const char *s = *p; bool neg = false; long v = 0; int digits = 0;
    if (*s == '-') { neg = true; s++; }
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; if (++digits > 6) return false; }
    if (!digits) return false;
    v = neg ? -v : v;
    if (v < lo || v > hi) return false;
    *out = v; *p = s; return true;
}

static bool parse(const vision_link_t *v, vision_frame_t *f)
{
    /* buf = "B,x,y,f*XX" */
    const char *star = 0; uint8_t ck = 0;
    for (uint8_t i = 0; i < v->n; i++) { if (v->buf[i] == '*') { star = &v->buf[i]; break; } ck ^= (uint8_t)v->buf[i]; }
    if (!star || (star - v->buf) + 3 != v->n) return false;
    int h = hexv(star[1]), l = hexv(star[2]);
    if (h < 0 || l < 0 || (uint8_t)(h * 16 + l) != ck) return false;
    const char *p = v->buf;
    long x, y, fd;
    if (*p++ != 'B' || *p++ != ',') return false;
    if (!parse_int(&p, -32768, 32767, &x) || *p++ != ',') return false;
    if (!parse_int(&p, -32768, 32767, &y) || *p++ != ',') return false;
    if (!parse_int(&p, 0, 1, &fd) || p != star) return false;
    f->x = (int16_t)x; f->y = (int16_t)y; f->found = fd == 1;
    return true;
}

bool vision_link_feed(vision_link_t *v, uint8_t c, vision_frame_t *out)
{
    if (c == '$') { if (v->in_frame) v->bad++; v->in_frame = true; v->n = 0; return false; }
    if (!v->in_frame) return false;
    if (c == '\n' || c == '\r') {
        v->in_frame = false;
        vision_frame_t f;
        if (parse(v, &f)) { v->good++; if (out) *out = f; return true; }
        v->bad++; return false;
    }
    if (v->n >= sizeof v->buf) { v->in_frame = false; v->bad++; return false; }
    v->buf[v->n++] = (char)c;
    return false;
}

int vision_link_format(char *buf, unsigned size, const vision_frame_t *f)
{
    char body[32];
    int n = snprintf(body, sizeof body, "B,%d,%d,%d", f->x, f->y, f->found ? 1 : 0);
    uint8_t ck = 0;
    for (int i = 0; i < n; i++) ck ^= (uint8_t)body[i];
    return snprintf(buf, size, "$%s*%02X\n", body, ck);
}
