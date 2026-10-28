#!/usr/bin/env python3
"""从 Press Start 2P（SIL OFL 1.1 像素字体，8×8 网格）渲染 ASCII 0x20..0x7E，生成 SSD1306 列字节表。
每字 8 字节，第 i 字节是第 i 列，bit0 = 顶行（与 SSD1306 页模式一致）。
用法：gen_font8x8.py <PressStart2P-Regular.ttf> > firmware/drivers/ssd1306/font8x8.c
"""
import sys
from PIL import Image, ImageDraw, ImageFont

f = ImageFont.truetype(sys.argv[1], 8)
print("/* 由 tools/gen_font8x8.py 生成，勿手改。字形来自 Press Start 2P（CodeMan38，SIL Open Font License 1.1，"
      "https://fonts.google.com/specimen/Press+Start+2P）。 */")
print('#include "ssd1306.h"\n\nconst uint8_t ssd1306_font8x8[95][8] = {')
for c in range(0x20, 0x7F):
    im = Image.new("1", (8, 8), 0)
    ImageDraw.Draw(im).text((0, 0), chr(c), font=f, fill=1)
    cols = [sum(1 << y for y in range(8) if im.getpixel((x, y))) for x in range(8)]
    esc = chr(c).replace("\\", "backslash")
    print("    {" + ", ".join(f"0x{v:02X}" for v in cols) + "}, /* " + (esc if c != 0x2F else "slash") + " */")
print("};")
