/**
 * @file menu.h
 * @brief 显示无关的页面、菜单项、导航、滚动和动作回调接口。
 */
#ifndef MENU_H
#define MENU_H

#include <stdbool.h>
#include <stddef.h>

#include "modules/display/display.h"

/** 菜单动作回调，由应用层提供具体业务。 */
typedef void (*Menu_Action_t)(void *context);

typedef struct MenuPage MenuPage;

/** 一个菜单条目可以进入子页面，也可以执行动作回调。 */
typedef struct {
    const char *label;
    const MenuPage *submenu;
    Menu_Action_t action;
    void *context;
} MenuItem;

/** 菜单页面由标题和静态条目数组组成。 */
struct MenuPage {
    const char *title;
    const MenuItem *items;
    size_t item_count;
};

/** Menu 模块的不透明控制器实例。 */
typedef struct MenuInstance MenuInstance;

/** 注册根菜单并绑定一个已经初始化的 OLED 或 TFT 显示适配器。 */
MenuInstance *MenuRegister(
    DisplayInstance *display, const MenuPage *root_page);

/** 循环移动到下一条菜单项。 */
bool MenuMoveNext(MenuInstance *instance);

/** 循环移动到上一条菜单项。 */
bool MenuMovePrevious(MenuInstance *instance);

/** 进入所选子菜单或执行所选动作。 */
bool MenuSelect(MenuInstance *instance);

/** 返回上一层页面；已经位于根页面时返回 false。 */
bool MenuBack(MenuInstance *instance);

/**
 * 从根页面搜索并定位到指定页面。
 * 成功后会重建完整的父子页面路径，后续仍可使用 MenuBack()。
 */
bool MenuNavigateToPage(
    MenuInstance *instance, const MenuPage *target_page);

/** 返回当前菜单路径深度；根页面深度为 1。 */
size_t MenuGetDepth(const MenuInstance *instance);

/** 将当前菜单页面绘制并刷新到当前显示设备。 */
bool MenuRender(MenuInstance *instance);

#endif
