/* STM32F407 链接脚本（自写，最小化）。Flash 长度由 Makefile 通过 -Wl,--defsym=__flash_kb=N 传入，
 * 掉电保存区 mcu.nvm_kb（--defsym=__nvm_kb，0/32/48）= 扇区 1..3（各 16 KB，0x08004000 起）：
 * 扇区 0 只放中断向量表，.text 从保存区之后开始（F4 后面的扇区是 128 KB，放在末尾太浪费）。
 * 取 board.yaml 的 mcu.flash_kb。只使用 128KB 主 SRAM；64KB CCM 暂不使用（DMA 访问不到 CCM）。 */
ENTRY(Reset_Handler)

__flash_kb = DEFINED(__flash_kb) ? __flash_kb : 512;
__nvm_kb = DEFINED(__nvm_kb) ? __nvm_kb : 0;
_Min_Heap_Size  = 0x400;
_Min_Stack_Size = 0x1000;

MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 1024K
  RAM   (xrw) : ORIGIN = 0x20000000, LENGTH = 128K
}
ASSERT(__flash_kb <= 1024, "flash_kb 超出 F407 最大 1MB")
ASSERT(__nvm_kb == 0 || __nvm_kb == 32 || __nvm_kb == 48, "F4 nvm_kb 只能 0/32/48（扇区 1..3，每个 16 KB）")

_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
  .isr_vector : { . = ALIGN(4); KEEP(*(.isr_vector)) . = ALIGN(4); } >FLASH

  .text (__nvm_kb > 0 ? ORIGIN(FLASH) + 16K + __nvm_kb * 1024 : .) :
  {
    . = ALIGN(4);
    *(.text) *(.text*) *(.glue_7) *(.glue_7t) *(.eh_frame)
    KEEP(*(.init)) KEEP(*(.fini))
    . = ALIGN(4);
    _etext = .;
  } >FLASH

  ASSERT(__nvm_kb == 0 || SIZEOF(.isr_vector) <= 16K, "中断向量表超出扇区 0")
  .rodata : { . = ALIGN(4); *(.rodata) *(.rodata*) . = ALIGN(4); } >FLASH

  .ARM.extab : { *(.ARM.extab* .gnu.linkonce.armextab.*) } >FLASH
  .ARM : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } >FLASH

  .preinit_array : { PROVIDE_HIDDEN(__preinit_array_start = .); KEEP(*(.preinit_array*)) PROVIDE_HIDDEN(__preinit_array_end = .); } >FLASH
  .init_array : { PROVIDE_HIDDEN(__init_array_start = .); KEEP(*(SORT(.init_array.*))) KEEP(*(.init_array*)) PROVIDE_HIDDEN(__init_array_end = .); } >FLASH
  .fini_array : { PROVIDE_HIDDEN(__fini_array_start = .); KEEP(*(SORT(.fini_array.*))) KEEP(*(.fini_array*)) PROVIDE_HIDDEN(__fini_array_end = .); } >FLASH

  _sidata = LOADADDR(.data);
  .data :
  {
    . = ALIGN(4);
    _sdata = .;
    *(.data) *(.data*)
    . = ALIGN(4);
    _edata = .;
  } >RAM AT> FLASH

  .bss :
  {
    . = ALIGN(4);
    _sbss = .; __bss_start__ = _sbss;
    *(.bss) *(.bss*) *(COMMON)
    . = ALIGN(4);
    _ebss = .; __bss_end__ = _ebss;
  } >RAM

  ._user_heap_stack :
  {
    . = ALIGN(8);
    PROVIDE(end = .); PROVIDE(_end = .);
    . = . + _Min_Heap_Size;
    . = . + _Min_Stack_Size;
    . = ALIGN(8);
  } >RAM

  ASSERT(_etext - ORIGIN(FLASH) + SIZEOF(.data) <= __flash_kb * 1024, "程序超出本板 Flash 容量（board.yaml mcu.flash_kb）")

  .ARM.attributes 0 : { *(.ARM.attributes) }
}
