# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b fontgen.py
"""
波特律动字模生成与 font.c 集成。

取模数据优先来自波特律动官方接口（与 led.baud-dance.com 取模助手 / 串口助手
完全一致的输出），接口不可用时回退到本地 PIL 渲染（离线兜底）。

字库条目格式（波特律动OLED驱动模板，与工程 font.c 一致）：
    /* N 字符 */ {0x<utf8_1>,0x<utf8_2>,0x<utf8_3>,0x00, <width*ceil(height/8) 字节点阵>,},
    即前 4 字节为 UTF-8 编码（3 字节 + 1 填充），剩余字节为点阵数据。
点阵为「列行式 / 阳码」：按列从左到右，每列 ceil(height/8) 字节，
字节内低位对应上方行像素，置 1 表示点亮。
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

API_URL = "https://led.baud-dance.com/api/glyph"

# 波特律动「字体取模」的文泉驿点阵字号 → (宽, 高)
FONT_FACES = {
    "wenquanyi_12pt": (16, 16),  # 文泉驿·点阵字16
    "wenquanyi_11pt": (15, 15),  # 文泉驿·点阵字15
    "wenquanyi_13px": (14, 14),  # 文泉驿·点阵字14
    "wenquanyi_10pt": (13, 13),  # 文泉驿·点阵字13
    "wenquanyi_9pt": (12, 12),   # 文泉驿·点阵字12
}

MODES = ("列行式", "行列式", "逐列式", "逐行式")
COLORS = ("阳码", "阴码")

# 兼容不规范的 font.c 条目：/* N 字符 */ {0x..,0x..,..},  （可能带尾逗号）
_ENTRY_RE = re.compile(r"/\*\s*\d+\s+([^\s*/]+)\s*\*/\s*\{([^}]*)\},?")

_FONT_STRUCT_RE = re.compile(
    r"(const Font\s+\w+\s*=\s*\{[^{}]*\})(\s*;)"
)


def is_cjk(ch: str) -> bool:
    """是否为需要进中文字库表的宽字符（排除 ASCII）。"""
    return ord(ch) > 0x7F


def fetch_glyphs(text: str, font: str = "wenquanyi_12pt",
                 width: int = 16, height: int = 16,
                 mode: str = "列行式", color: str = "阳码",
                 timeout: float = 30.0) -> dict[str, list[int]]:
    """从波特律动官方接口获取字符点阵。

    返回 {字符: [字节列表]}，字节数与波特律动工具输出一致
    （列行式，每列 ceil(height/8) 字节，低位在上）。
    """
    if mode not in MODES:
        raise ValueError(f"不支持的取模方式: {mode}，可选 {MODES}")
    if color not in COLORS:
        raise ValueError(f"不支持的阴阳码: {color}，可选 {COLORS}")
    query = urllib.parse.urlencode({
        "font": font,
        "width": width,
        "height": height,
        "text": ",".join(text),
        "mode": mode,
        "color": color,
    })
    url = f"{API_URL}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"波特律动接口返回非 JSON: {body[:300]}") from e
    if not isinstance(data, dict) or data.get("code") != 200:
        raise RuntimeError(f"波特律动接口返回异常: {body[:300]}")
    d = data.get("data")
    if not isinstance(d, dict):
        raise RuntimeError(f"波特律动接口返回格式异常: {body[:300]}")
    out = {}
    for ch in text:
        vals = d.get(ch)
        if vals is None:
            raise RuntimeError(f"波特律动接口未返回字符 {ch} 的字模")
        out[ch] = [int(v) for v in vals]
    return out


def generate_local(text: str, width: int = 16, height: int = 16) -> dict[str, list[int]]:
    """本地 PIL 渲染点阵（离线兜底，格式与波特律动列行式/阳码一致）。"""
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "波特律动接口不可用，且本机无 Pillow 无法本地取模。"
            "请联网重试，或安装 Pillow (pip install pillow)"
        ) from e

    fonts = [
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
    ]
    face = None
    for fp in fonts:
        if __import__("os").path.exists(fp):
            try:
                face = ImageFont.truetype(fp, 26)
                break
            except Exception:
                continue
    if face is None:
        raise RuntimeError("未找到可用的中文字体（simhei/simsun/msyh）")
    per = (height + 7) // 8
    out = {}
    for ch in text:
        img = Image.new("L", (32, 32), 255)
        d = ImageDraw.Draw(img)
        d.text((16, 16), ch, font=face, fill=0, anchor="mm")
        bits = []
        for y in range(height):
            for x in range(width):
                dark = any(
                    img.getpixel((x * (32 // width) + dx, y * (32 // height) + dy)) < 128
                    for dy in range(32 // height)
                    for dx in range(32 // width)
                )
                bits.append(dark)
        glyph = []
        for x in range(width):
            for j in range(per):
                byte = 0
                for y in range(8):
                    yy = j * 8 + y
                    if yy < height and bits[yy * width + x]:
                        byte |= 1 << y
                glyph.append(byte)
        out[ch] = glyph
    return out


def glyph_preview(glyph: list[int], width: int = 16, height: int = 16,
                  invert: bool = False) -> str:
    """把点阵渲染成 ASCII 预览（'#'=点亮，'.'=熄灭）。"""
    per = (height + 7) // 8
    rows = []
    for y in range(height):
        line = []
        for x in range(width):
            byte = glyph[x * per + y // 8]
            lit = bool((byte >> (y % 8)) & 1)
            if invert:
                lit = not lit
            line.append("#" if lit else ".")
        rows.append("".join(line))
    return "\n".join(rows)


def build_entry(index: int, ch: str, glyph: list[int], entry_size: int) -> str:
    """生成单条 C 字模：/* N 字符 */ {utf8,0x00,32字节点阵,},"""
    data_len = entry_size - 4
    if len(glyph) != data_len:
        raise ValueError(
            f"字符 {ch} 字模长度 {len(glyph)} != 期望 {data_len}"
        )
    utf8 = ",".join("0x%02x" % b for b in ch.encode("utf-8"))
    body = ",".join("0x%02x" % v for v in glyph)
    return f"/* {index} {ch} */ {{{utf8},0x00,{body},}},"


def parse_entries(content: str) -> dict[str, list[int]]:
    """解析 font.c 中已有条目：{字符: [全部字节(含4字节utf8头)]}。"""
    out = {}
    for m in _ENTRY_RE.finditer(content):
        ch = m.group(1)
        try:
            bytes_ = [int(b, 16) for b in re.findall(r"0x[0-9a-fA-F]+", m.group(2))]
        except ValueError:
            continue
        if len(bytes_) >= 4 and bytes_[3] == 0:
            out[ch] = bytes_
    return out


def apply_to_font_c(font_c: str, items: list[str],
                    glyphs: dict[str, list[int]],
                    table: str = "zh16x16",
                    font_name: str = "font16x16") -> tuple[str, str]:
    """把字模条目追加进 font.c，并更新 Font 结构体 len。

    items: 需新增的字符列表（保持顺序）
    返回 (新文件内容, 报告文本)
    """
    start_m = re.search(
        r"(const uint8_t\s+" + re.escape(table) + r"\[\]\[\d+\]\s*=\s*\{)", font_c
    )
    if not start_m:
        raise RuntimeError(f"未在 font.c 找到数组 {table}[][N]")
    block_start = start_m.end()
    size_m = re.search(r"const uint8_t\s+" + re.escape(table) + r"\[\]\[(\d+)\]", font_c)
    entry_size = int(size_m.group(1)) if size_m else 36

    # 数组结束标记：条目之后独占一行的 "};"
    tail = font_c[block_start:]
    end_m = re.search(r"^\s*}\s*;", tail, re.MULTILINE)
    if not end_m:
        raise RuntimeError(f"未找到数组 {table} 的结束 '}};'")
    block_end = block_start + end_m.start()
    block = font_c[block_start:block_end]

    existing = parse_entries(block)
    cur_index = len(_ENTRY_RE.findall(block))

    new_items = [ch for ch in items if ch not in existing]
    skipped = [ch for ch in items if ch in existing]

    new_lines = []
    for ch in new_items:
        new_lines.append(build_entry(cur_index, ch, glyphs[ch], entry_size))
        cur_index += 1

    inserted = "\n".join(new_lines)
    new_block = block
    if new_lines:
        if not new_block.rstrip().endswith(","):
            new_block = new_block.rstrip() + ","
        new_block = new_block + "\n" + inserted
    new_content = font_c[:block_start] + new_block + font_c[block_end:]

    total = len(parse_entries(new_content))
    new_content = _update_len(new_content, table, font_name, entry_size, total)

    report = []
    report.append(
        f"字库 {table}（每字 {entry_size} 字节），原 {len(existing)} 字 → 现 {total} 字"
    )
    if new_items:
        report.append(f"新增 {len(new_lines)} 个字符: {''.join(new_items)}")
        report.append(f"追加条目:\n{inserted}")
    if skipped:
        report.append(f"跳过（已在字库中）: {''.join(skipped)}")
    return new_content, "\n".join(report)


def _update_len(content: str, table: str, font_name: str,
                entry_size: int, total: int) -> str:
    """更新 Font 结构体的 len 字段（兼容 .len= 命名式与位置式）。"""
    def repl(m: re.Match) -> str:
        block = m.group(1)
        if ".len" in block:
            block = re.sub(
                r"\.len\s*=\s*sizeof\([^)]*\)\s*/\s*\d+",
                f".len = sizeof({table})/{entry_size}",
                block,
            )
        else:
            block = re.sub(
                r"\(\s*const uint8_t\s*\*\s*\)(\w+)\s*,\s*\d+,",
                f"(const uint8_t *){table}, {total},",
                block,
            )
        return block + m.group(2)

    return _FONT_STRUCT_RE.sub(repl, content)


def add_chars_to_font_c(font_c_path: str, text: str,
                        font: str = "wenquanyi_12pt",
                        width: int = 16, height: int = 16,
                        mode: str = "列行式", color: str = "阳码") -> str:
    """一站式：取模 + 集成进 font.c（失败自动回退本地 PIL）。

    返回报告文本（含每字符 ASCII 预览）。
    """
    import os

    if not os.path.exists(font_c_path):
        raise FileNotFoundError(f"font.c 不存在: {font_c_path}")

    with open(font_c_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 仅处理宽字符，保留输入顺序，去重
    chars = list(dict.fromkeys(c for c in text if is_cjk(c)))
    if not chars:
        raise ValueError("text 中没有需要生成字模的中文/宽字符")

    try:
        glyphs = fetch_glyphs(chars, font, width, height, mode, color)
        source = "波特律动官方接口"
    except Exception as e:
        glyphs = generate_local(chars, width, height)
        source = f"本地 PIL 渲染（官方接口不可用: {type(e).__name__}: {e}）"

    new_content, report = apply_to_font_c(content, chars, glyphs)
    with open(font_c_path, "w", encoding="utf-8", newline="") as f:
        f.write(new_content)

    existing = parse_entries(content)
    added = [ch for ch in chars if ch not in existing]

    invert = color == "阴码"
    lines = [report, "", f"数据来源: {source}"]
    for ch in added:
        lines.append("")
        lines.append(f"── {ch} ──")
        lines.append(glyph_preview(glyphs[ch], width, height, invert))
    return "\n".join(lines)
