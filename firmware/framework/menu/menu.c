/**
 * @file menu.c
 * @brief 见 menu.h。
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/menu/menu.c （MIT，Copyright (c) 2026 阡陌）
 */
#include "menu.h"
#include <math.h>
#include <string.h>

static bool page_ok(const menu_page_t *p) { return p && p->title && (p->n == 0u || p->items); }
static bool ok(const menu_t *m) { return m && m->depth > 0u && m->depth <= MENU_MAX_DEPTH && page_ok(m->stack[m->depth - 1u]); }
static uint8_t visible(const menu_t *m) { return (uint8_t)((m->view && m->view->rows > 1u) ? m->view->rows - 1u : 1u); }

dz_err_t menu_init(menu_t *m, const menu_page_t *root, const menu_view_t *view)
{
    if (!m || !page_ok(root) || (view && (view->rows < 2u || view->cols == 0u || view->cols > MENU_MAX_COLS))) return DZ_EINVAL;
    memset(m, 0, sizeof *m);
    m->stack[0] = root; m->depth = 1; m->view = view;
    return DZ_OK;
}

static void sync_window(menu_t *m)        /* 原版 MenuSynchronizeWindow */
{
    uint8_t d = m->depth - 1u, s = m->sel[d], v = visible(m);
    if (s < m->first[d]) m->first[d] = s;
    else if (s >= m->first[d] + v) m->first[d] = (uint8_t)(s - v + 1u);
}

bool menu_next(menu_t *m)
{
    if (!ok(m) || m->editing) return false;
    const menu_page_t *p = m->stack[m->depth - 1u];
    if (!p->n) return false;
    m->sel[m->depth - 1u] = (uint8_t)((m->sel[m->depth - 1u] + 1u) % p->n);
    sync_window(m);
    return true;
}

bool menu_prev(menu_t *m)
{
    if (!ok(m) || m->editing) return false;
    const menu_page_t *p = m->stack[m->depth - 1u];
    if (!p->n) return false;
    uint8_t *s = &m->sel[m->depth - 1u];
    *s = *s == 0u ? (uint8_t)(p->n - 1u) : (uint8_t)(*s - 1u);
    sync_window(m);
    return true;
}

const menu_page_t *menu_page(const menu_t *m) { return ok(m) ? m->stack[m->depth - 1u] : NULL; }

const menu_item_t *menu_current(const menu_t *m)
{
    const menu_page_t *p = menu_page(m);
    if (!p || !p->n || m->sel[m->depth - 1u] >= p->n) return NULL;
    return &p->items[m->sel[m->depth - 1u]];
}

bool menu_select(menu_t *m)
{
    const menu_item_t *it = menu_current(m);
    if (!it) return false;
    if (it->sub) {
        if (!page_ok(it->sub) || m->depth >= MENU_MAX_DEPTH) return false;
        m->stack[m->depth] = it->sub; m->sel[m->depth] = 0; m->first[m->depth] = 0; m->depth++;
        return true;
    }
    if (it->action) { it->action(it->ctx); return true; }
    if (it->value) { m->editing = !m->editing; return true; }
    return false;
}

bool menu_back(menu_t *m)
{
    if (!ok(m)) return false;
    if (m->editing) { m->editing = false; return true; }
    if (m->depth <= 1u) return false;
    m->depth--;
    return true;
}

static bool find(const menu_page_t *cur, const menu_page_t *t, const menu_page_t **path, uint8_t d, uint8_t *out)
{
    if (!page_ok(cur) || d >= MENU_MAX_DEPTH) return false;          /* 限深，防循环菜单无限递归 */
    path[d] = cur;
    if (cur == t) { *out = (uint8_t)(d + 1u); return true; }
    for (uint8_t i = 0; i < cur->n; i++)
        if (cur->items[i].sub && find(cur->items[i].sub, t, path, (uint8_t)(d + 1u), out)) return true;
    return false;
}

bool menu_goto(menu_t *m, const menu_page_t *t)
{
    const menu_page_t *path[MENU_MAX_DEPTH];
    uint8_t n = 0;
    if (!ok(m) || !page_ok(t) || !find(m->stack[0], t, path, 0, &n)) return false;
    for (uint8_t i = 0; i < n; i++) { m->stack[i] = path[i]; m->sel[i] = 0; m->first[i] = 0; }
    m->depth = n; m->editing = false;
    return true;
}

static bool edit(menu_t *m, float dir)
{
    const menu_item_t *it = menu_current(m);
    if (!it || !it->value || !isfinite(*it->value)) return false;
    float v = *it->value + dir * it->step;
    if (v > it->max) v = it->max;
    if (v < it->min) v = it->min;
    *it->value = v;
    return true;
}

bool menu_input(menu_t *m, menu_in_t in)
{
    switch (in) {
    case MENU_IN_UP:   return m && m->editing ? edit(m, +1.0f) : menu_prev(m);
    case MENU_IN_DOWN: return m && m->editing ? edit(m, -1.0f) : menu_next(m);
    case MENU_IN_OK:   return menu_select(m);
    case MENU_IN_BACK: return menu_back(m);
    }
    return false;
}

uint8_t menu_depth(const menu_t *m) { return ok(m) ? m->depth : 0u; }

/* 不用 snprintf（newlib-nano 默认不带 %f，且体积大）：自写拼接 + 两位小数 */
typedef struct { char *b; uint8_t n, cap; } sb_t;
static void put(sb_t *s, const char *t) { while (t && *t && s->n < s->cap) s->b[s->n++] = *t++; s->b[s->n] = '\0'; }
static void put_f(sb_t *s, float v)
{
    char t[16]; uint8_t k = 0;
    if (!isfinite(v)) { put(s, "nan"); return; }
    if (v < 0.0f) { put(s, "-"); v = -v; }
    uint32_t c = (uint32_t)lroundf(v * 100.0f), ip = c / 100u, fp = c % 100u;
    do { t[k++] = (char)('0' + ip % 10u); ip /= 10u; } while (ip && k < 10u);
    char o[16]; uint8_t j = 0;
    while (k) o[j++] = t[--k];
    if (fp) { o[j++] = '.'; o[j++] = (char)('0' + fp / 10u); if (fp % 10u) o[j++] = (char)('0' + fp % 10u); }
    o[j] = '\0';
    put(s, o);
}

dz_err_t menu_render(const menu_t *m)
{
    if (!ok(m) || !m->view || !m->view->line) return DZ_EINVAL;
    const menu_view_t *v = m->view;
    const menu_page_t *p = m->stack[m->depth - 1u];
    char buf[MENU_MAX_COLS + 1u];
    uint8_t d = m->depth - 1u;
    if (v->clear) v->clear(v->ctx);
    sb_t sb = { buf, 0, v->cols };
    buf[0] = '\0';
    put(&sb, p->title);                                                   /* 截断，不换行 */
    v->line(v->ctx, 0, buf, false);
    for (uint8_t r = 0; r < visible(m); r++) {
        uint8_t i = (uint8_t)(m->first[d] + r);
        if (i >= p->n) break;
        const menu_item_t *it = &p->items[i];
        bool sel = i == m->sel[d];
        sb.n = 0; buf[0] = '\0';
        put(&sb, sel ? (m->editing ? "*" : ">") : " ");
        put(&sb, it->label);
        if (it->value) { put(&sb, " "); put_f(&sb, *it->value); }
        else if (it->sub) put(&sb, " >");
        v->line(v->ctx, (uint8_t)(r + 1u), buf, sel);
    }
    if (v->flush) v->flush(v->ctx);
    return DZ_OK;
}

dz_err_t menu_selftest(void)
{
    static const menu_item_t sub_items[] = { { "a", NULL, NULL, NULL, NULL, 0, 0, 0 } };
    static const menu_page_t sub = { "sub", sub_items, 1 };
    static const menu_item_t root_items[] = { { "go", &sub, NULL, NULL, NULL, 0, 0, 0 } };
    static const menu_page_t root = { "root", root_items, 1 };
    menu_t m;
    if (menu_init(&m, &root, NULL) || !menu_select(&m) || menu_depth(&m) != 2u || !menu_back(&m) || menu_back(&m)) return DZ_EFAIL;
    return DZ_OK;
}
