# 链接脚本：MEMORY 写系列最大值，容量靠 __flash_kb ASSERT 卡住

- **决定**：`*_FLASH.ld` 的 `FLASH LENGTH` 写芯片系列上限（F103x8/xB 128K、F407 1M），真实容量由 Makefile `--defsym=__flash_kb=<board.yaml mcu.flash_kb>` 传入，脚本末尾 `ASSERT(程序 <= __flash_kb*1024)`。
- **为什么**：同一份链接脚本给 VET6（512K）和 VGT6（1M）共用，换型号只改 board.yaml 一个数。
- **证据**：`make BOARD=stm32f103c8t6-car-cubemx APP=car_2wd BOARD_FLASH_KB=8` → 链接报"程序超出本板 Flash 容量"（2026-10-29 本机）。
- **守护**：`tools/check_gen_consistency.py` C3 检查 ASSERT 存在。
- **代价**：`arm-none-eabi-size`/链接器内存报告的百分比按 LENGTH 算，看起来偏小。
- **否决过**：把 LENGTH 改成与 flash_kb 相等（docs/27 初稿的 G1 建议）——会让 VGT6 要另一份脚本，且现有 ASSERT 已经能拦住超限。
