# menu — 板上菜单（与显示无关）  `v1.0.0`

静态页面树 + 页面栈：上下循环移动、滚动窗口、进子页 / 执行动作、返回、按页面直接跳转；**数值编辑项**
（指向一个 float，选中后上下键按步长改值、限幅，再按确定/返回退出）。画屏交给 `menu_view_t` 回调，
OLED（drivers/ssd1306）、TFT（drivers/st77xx）、串口打印都能接；不用 printf。

- 输入：`menu_input(&m, MENU_IN_UP/DOWN/OK/BACK)`，返回 true 就 `menu_render`。按键来源随意：独立按键（drivers/key）、4×4 键盘（drivers/keypad4x4）、编码器旋钮。
- 选中行前缀 `>`，编辑中为 `*`；子页条目末尾 ` >`。
- 板上改的参数如果也想让工作台看到：数值项直接指向 dzctl 注册的参数变量即可（同一块内存）。
- 主机测试 tests/host/test_signal.c（用字符缓冲当“屏幕”逐行比对）

## 验证状态
- **已实测（PC 主机）**：导航、滚动、深度上限、goto 重建路径、编辑限幅、截断显示。
- **【未测】上板**（还没接进任何 app）。

## 参考来源
LP-MSPM0G3507_freertos_firework@ede35a2 `modules/menu/menu.c`（MIT，阡陌）直接移植并扩展（见文件头）。
