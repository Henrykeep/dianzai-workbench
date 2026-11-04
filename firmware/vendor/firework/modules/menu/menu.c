/*
 * Menu Module 管理静态页面树、选中项、滚动窗口、子页进入和动作回调，不包含业务逻辑。
 */
#include "modules/menu/menu.h"

#include <stddef.h>

#define MENU_MAX_DEPTH          (6U)
#define MENU_VISIBLE_ITEM_COUNT (6U)
#define MENU_TITLE_Y            (0U)
#define MENU_SEPARATOR_Y        (9U)
#define MENU_FIRST_ITEM_Y       (12U)
#define MENU_ITEM_HEIGHT        (8U)
#define MENU_LABEL_X            (8U)
#define MENU_MAX_TITLE_CHARS    (18U)
#define MENU_MAX_LABEL_CHARS    (19U)

struct MenuInstance {
    /* 菜单绘制目标。 */
    DisplayInstance *display;
    /* 页面栈保存当前位置以及每层的选择和滚动状态。 */
    const MenuPage *page_stack[MENU_MAX_DEPTH];
    size_t selected_stack[MENU_MAX_DEPTH];
    size_t first_visible_stack[MENU_MAX_DEPTH];
    size_t depth;
    bool registered;
};

/* 当前项目只需要一个菜单控制器。 */
static MenuInstance menu_instance;

static bool MenuIsValid(const MenuInstance *instance);
static bool MenuPageIsValid(const MenuPage *page);
static bool MenuFindPagePath(const MenuPage *current_page,
    const MenuPage *target_page, const MenuPage **page_path,
    size_t depth, size_t *path_depth);
static void MenuSynchronizeWindow(MenuInstance *instance);
static bool MenuDrawClippedText(DisplayInstance *display,
    uint8_t x, uint8_t y,
    const char *text, size_t maximum_characters);

/* 注册通用菜单控制器并将根页面压入页面栈。 */
MenuInstance *MenuRegister(
    DisplayInstance *display, const MenuPage *root_page)
{
    if ((display == NULL) || !MenuPageIsValid(root_page)) {
        return NULL;
    }

    if (menu_instance.registered) {
        return (menu_instance.display == display) ? &menu_instance : NULL;
    }

    menu_instance.display                = display;
    menu_instance.page_stack[0]          = root_page;
    menu_instance.selected_stack[0]      = 0U;
    menu_instance.first_visible_stack[0] = 0U;
    menu_instance.depth                  = 1U;
    menu_instance.registered             = true;
    return &menu_instance;
}

/* 将当前选择循环移动到下一项。 */
bool MenuMoveNext(MenuInstance *instance)
{
    const MenuPage *page;
    size_t *selected;

    if (!MenuIsValid(instance)) {
        return false;
    }

    page     = instance->page_stack[instance->depth - 1U];
    selected = &instance->selected_stack[instance->depth - 1U];

    if (page->item_count == 0U) {
        return false;
    }

    *selected = (*selected + 1U) % page->item_count;
    MenuSynchronizeWindow(instance);
    return true;
}

/* 将当前选择循环移动到上一项。 */
bool MenuMovePrevious(MenuInstance *instance)
{
    const MenuPage *page;
    size_t *selected;

    if (!MenuIsValid(instance)) {
        return false;
    }

    page     = instance->page_stack[instance->depth - 1U];
    selected = &instance->selected_stack[instance->depth - 1U];

    if (page->item_count == 0U) {
        return false;
    }

    *selected = (*selected == 0U) ? page->item_count - 1U
                                  : *selected - 1U;
    MenuSynchronizeWindow(instance);
    return true;
}

/* 进入子页面或调用当前条目的应用动作。 */
bool MenuSelect(MenuInstance *instance)
{
    const MenuPage *page;
    const MenuItem *item;
    size_t selected;

    if (!MenuIsValid(instance)) {
        return false;
    }

    page     = instance->page_stack[instance->depth - 1U];
    selected = instance->selected_stack[instance->depth - 1U];

    if ((page->item_count == 0U) || (selected >= page->item_count)) {
        return false;
    }

    item = &page->items[selected];
    if (item->submenu != NULL) {
        if (!MenuPageIsValid(item->submenu) ||
            (instance->depth >= MENU_MAX_DEPTH)) {
            return false;
        }

        instance->page_stack[instance->depth]          = item->submenu;
        instance->selected_stack[instance->depth]      = 0U;
        instance->first_visible_stack[instance->depth] = 0U;
        ++instance->depth;
        return true;
    }

    if (item->action != NULL) {
        item->action(item->context);
        return true;
    }

    return false;
}

/* 从页面栈弹出当前页面，返回上一层菜单。 */
bool MenuBack(MenuInstance *instance)
{
    if (!MenuIsValid(instance) || (instance->depth <= 1U)) {
        return false;
    }

    --instance->depth;
    return true;
}

/* 从根页面递归查找目标，并恢复可逐层返回的完整路径。 */
bool MenuNavigateToPage(
    MenuInstance *instance, const MenuPage *target_page)
{
    const MenuPage *page_path[MENU_MAX_DEPTH];
    size_t path_depth = 0U;
    size_t index;

    if (!MenuIsValid(instance) || !MenuPageIsValid(target_page) ||
        !MenuFindPagePath(instance->page_stack[0], target_page,
            page_path, 0U, &path_depth)) {
        return false;
    }

    for (index = 0U; index < path_depth; ++index) {
        instance->page_stack[index]          = page_path[index];
        instance->selected_stack[index]      = 0U;
        instance->first_visible_stack[index] = 0U;
    }
    instance->depth = path_depth;
    return true;
}

size_t MenuGetDepth(const MenuInstance *instance)
{
    return MenuIsValid(instance) ? instance->depth : 0U;
}

/* 绘制标题、分隔线、可见条目以及当前选择箭头。 */
bool MenuRender(MenuInstance *instance)
{
    const MenuPage *page;
    size_t first_visible;
    size_t selected;
    size_t visible_index;
    uint8_t x;

    if (!MenuIsValid(instance) ||
        !DisplayClear(instance->display, false)) {
        return false;
    }

    page          = instance->page_stack[instance->depth - 1U];
    selected      = instance->selected_stack[instance->depth - 1U];
    first_visible = instance->first_visible_stack[instance->depth - 1U];

    if (!MenuDrawClippedText(instance->display,
            0U, MENU_TITLE_Y, page->title,
            MENU_MAX_TITLE_CHARS)) {
        return false;
    }

    for (x = 0U; x < DISPLAY_WIDTH; ++x) {
        (void)DisplaySetPixel(
            instance->display, x, MENU_SEPARATOR_Y, true);
    }

    for (visible_index = 0U;
         visible_index < MENU_VISIBLE_ITEM_COUNT;
         ++visible_index) {
        size_t item_index = first_visible + visible_index;
        uint8_t y = (uint8_t)(MENU_FIRST_ITEM_Y +
                              (visible_index * MENU_ITEM_HEIGHT));

        if (item_index >= page->item_count) {
            break;
        }

        if (item_index == selected) {
            (void)DisplayDrawCharacter(
                instance->display, 0U, y, '>');
        }

        if (!MenuDrawClippedText(instance->display, MENU_LABEL_X, y,
                page->items[item_index].label, MENU_MAX_LABEL_CHARS)) {
            return false;
        }
    }

    return DisplayUpdate(instance->display);
}

/* 检查菜单控制器和当前页面状态是否有效。 */
static bool MenuIsValid(const MenuInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->display != NULL) && (instance->depth > 0U) &&
           (instance->depth <= MENU_MAX_DEPTH) &&
           MenuPageIsValid(instance->page_stack[instance->depth - 1U]);
}

/* 检查静态页面描述是否具备标题和合法条目数组。 */
static bool MenuPageIsValid(const MenuPage *page)
{
    return (page != NULL) && (page->title != NULL) &&
           ((page->item_count == 0U) || (page->items != NULL));
}

/* 深度受 MENU_MAX_DEPTH 限制，同时防止异常循环菜单无限递归。 */
static bool MenuFindPagePath(const MenuPage *current_page,
    const MenuPage *target_page, const MenuPage **page_path,
    size_t depth, size_t *path_depth)
{
    size_t item_index;

    if (!MenuPageIsValid(current_page) || (target_page == NULL) ||
        (page_path == NULL) || (path_depth == NULL) ||
        (depth >= MENU_MAX_DEPTH)) {
        return false;
    }

    page_path[depth] = current_page;
    if (current_page == target_page) {
        *path_depth = depth + 1U;
        return true;
    }

    for (item_index = 0U;
         item_index < current_page->item_count;
         ++item_index) {
        const MenuPage *submenu = current_page->items[item_index].submenu;

        if ((submenu != NULL) &&
            MenuFindPagePath(submenu, target_page, page_path,
                depth + 1U, path_depth)) {
            return true;
        }
    }
    return false;
}

/* 调整当前页面的首个可见条目，确保选中项始终位于屏幕中。 */
static void MenuSynchronizeWindow(MenuInstance *instance)
{
    size_t depth_index = instance->depth - 1U;
    size_t selected = instance->selected_stack[depth_index];
    size_t *first_visible = &instance->first_visible_stack[depth_index];

    if (selected < *first_visible) {
        *first_visible = selected;
    } else if (selected >= (*first_visible + MENU_VISIBLE_ITEM_COUNT)) {
        *first_visible = selected - MENU_VISIBLE_ITEM_COUNT + 1U;
    }
}

/* 将字符串截断到指定字符数后绘制，避免标题或条目自动换行。 */
static bool MenuDrawClippedText(DisplayInstance *display,
    uint8_t x, uint8_t y,
    const char *text, size_t maximum_characters)
{
    char buffer[MENU_MAX_LABEL_CHARS + 1U];
    size_t index = 0U;

    if ((display == NULL) || (text == NULL) ||
        (maximum_characters > MENU_MAX_LABEL_CHARS)) {
        return false;
    }

    while ((text[index] != '\0') && (index < maximum_characters)) {
        buffer[index] = text[index];
        ++index;
    }
    buffer[index] = '\0';

    return DisplayDrawString(display, x, y, buffer);
}
