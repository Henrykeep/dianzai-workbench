# Menu Module 使用指南

`modules/menu/` 提供与具体业务和显示器无关的多级菜单状态机。Application层负责定义
静态页面、条目和动作回调，Module负责选择、滚动、页面栈和绘制。

## 1. 页面和条目结构

```c
typedef struct {
    const char *label;
    const MenuPage *submenu;
    Menu_Action_t action;
    void *context;
} MenuItem;

struct MenuPage {
    const char *title;
    const MenuItem *items;
    size_t item_count;
};
```

一个条目可以进入 `submenu`，也可以执行 `action`。如果两者都设置，Module优先进入
子菜单；如果两者都为NULL，选择该条目返回 `false`。

## 2. 定义静态菜单

```c
#include <stdint.h>

#include "modules/menu/menu.h"

static void ExampleAction(void *context)
{
    uint32_t *counter = (uint32_t *)context;
    ++(*counter);
}

static uint32_t action_count;

static const MenuItem settings_items[] = {
    {"RUN ACTION", NULL, ExampleAction, &action_count}
};

static const MenuPage settings_page = {
    "SETTINGS",
    settings_items,
    sizeof(settings_items) / sizeof(settings_items[0])
};

static const MenuItem root_items[] = {
    {"SETTINGS", &settings_page, NULL, NULL}
};

static const MenuPage root_page = {
    "MAIN MENU",
    root_items,
    sizeof(root_items) / sizeof(root_items[0])
};
```

页面、条目、标题和标签必须在菜单使用期间一直有效，因此建议定义为 `static const`，
不要使用函数栈上的临时数组或字符串。

## 3. 注册和首次绘制

```c
static MenuInstance *menu;

menu = MenuRegister(initialized_display, &root_page);
if (menu != NULL) {
    (void)MenuRender(menu);
}
```

`initialized_display` 必须由 `OLEDDisplayInit()` 或 `TFTDisplayInit()` 先完成
后端初始化并取得 `DisplayInstance` 适配器。当前 Module 只提供一个静态菜单
实例；重复注册同一显示适配器会返回已有实例，换成另一个则失败。

## 4. 导航接口

```c
if (MenuMoveNext(menu)) {
    (void)MenuRender(menu);
}

if (MenuMovePrevious(menu)) {
    (void)MenuRender(menu);
}

if (MenuSelect(menu)) {
    (void)MenuRender(menu);
}

if (MenuBack(menu)) {
    (void)MenuRender(menu);
}
```

移动和返回接口只修改菜单状态，不会自动刷新屏幕。进入子菜单后通常需要调用
`MenuRender()`；动作回调如果切换到波形等其他界面，可以由Application决定是否继续
渲染菜单。

如果Application需要从自定义页直接定位到某个子菜单，可以使用：

```c
if (MenuNavigateToPage(menu, &settings_page)) {
    size_t entry_depth = MenuGetDepth(menu);
    (void)MenuRender(menu);
}
```

`MenuNavigateToPage()` 会从根页搜索目标页，并重建完整父子路径；因此定位后
仍可正常调用 `MenuBack()` 逐层返回。根页深度为 `1U`，搜索不到目标时
不会修改当前菜单状态。

## 5. 固定显示限制

- 页面栈最多6层，根页面占1层。
- 屏幕一次显示6个条目，超过后自动滚动窗口。
- 标题最多绘制18个字符。
- 条目标签最多绘制19个字符。
- 当前字体只支持ASCII，不支持直接显示中文。
- 上一项和下一项会首尾循环。

## 6. 任务和回调注意事项

- Menu本身不创建任务，应由Application按键任务调用。
- 当前实例没有互斥锁，导航和绘制建议固定在同一个任务完成。
- 动作回调在调用 `MenuSelect()` 的任务上下文中同步执行，不能长时间阻塞。
- 动作回调不要保存指向临时栈变量的 `context`。
- 已在根页面时调用 `MenuBack()` 返回 `false`。
