/* 掉电保存区守卫（和 SDK 的 mspm0g3507.lds 一起传给链接器，不改 SDK 文件）：
 * 程序（.text…+ .data 初值）不能伸进 Flash 末尾 mcu.nvm_kb 的保存区。__nvm_kb/__flash_kb 由 mk/mspm0-driverlib.mk --defsym 传入。 */
ASSERT(__data_load__ + (__data_end__ - __data_start__) <= (__flash_kb - __nvm_kb) * 1024, "程序侵占了掉电保存区（board.yaml mcu.nvm_kb）")
