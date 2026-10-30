#!/usr/bin/env python3
"""界面文案检查（问题池 #26）：扫 app/ui 里用户看得见的字符串。

禁止：「侧车」（对用户统一叫「本地服务」；变量名不管）、口语词（一下 / 搞 / 啥 …）、感叹号（！ 或中文旁的 !）、emoji。
范围：app/ui/index.html 的文字与 title/placeholder/aria-label/alt/value 属性；app/ui/src/**/*.ts 里含中文的字符串字面量
（注释不算）。用法：python3 tools/check_copy.py [--selftest]；有问题时逐条列出 文件:行 · 命中 · 原文 · 怎么改，退出码 1。
"""
import re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "app" / "ui"
CJK = re.compile(r"[\u4e00-\u9fff]")
COLLOQ = ["一下", "搞定", "搞", "啥", "咋", "弄", "瞅", "呗", "嘛", "啦", "咱"]
# emoji：表情 / 图形符号平面 + 常见的 ⚠ ⚡ ✅ ❌ ⭐ 与变体选择符；✓ ✗ 这类文字符号不算
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u26A0\u26A1\u2705\u274C\u2B50\uFE0F]")
FIX = {"侧车": "改成「本地服务」", "！": "去掉感叹号，用句号", "!": "去掉感叹号，用句号", "emoji": "去掉 emoji，用文字或图标组件"}


def ts_strings(src: str):
    """极简词法：跳过注释，产出 (行号, 字面量文本)。模板字符串的 ${...} 里递归处理。"""
    out, i, n, line = [], 0, len(src), 1
    stack = []  # 模板嵌套：每层记 ${ 的花括号深度
    depth = 0
    def read_str(q, i, line):
        start_line, buf = line, []
        i += 1
        while i < n:
            c = src[i]
            if c == "\\":
                buf.append(src[i:i + 2]); i += 2; continue
            if c == "\n":
                line += 1
            if q == "`" and src.startswith("${", i):
                out.append((start_line, "".join(buf)))
                return i + 2, line, True
            if c == q:
                out.append((start_line, "".join(buf)))
                return i + 1, line, False
            buf.append(c); i += 1
        return i, line, False
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2); seg = src[i:j if j >= 0 else n]; line += seg.count("\n"); i = n if j < 0 else j + 2; continue
        if c == "/" and _regex_ok(src, i):
            i = _skip_regex(src, i); continue
        if c in "\"'`":
            i, line, opened = read_str(c, i, line)
            if opened:
                stack.append(depth); depth = 0
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if stack and depth == 0:
                depth = stack.pop()
                i, line, opened = read_str("`", i, line)   # 回到模板文字部分（i 指向 } ，read_str 会先 +1）
                if opened:
                    stack.append(depth); depth = 0
                continue
            depth -= 1
        i += 1
    return out


def _regex_ok(src, i):
    j = i - 1
    while j >= 0 and src[j] in " \t":
        j -= 1
    if j < 0 or src[j] in "(,=:[!&|?{};\n+-*%<>~^":
        return True
    return bool(re.search(r"\b(return|typeof|case|in|of)$", src[max(0, j - 7):j + 1]))


def _skip_regex(src, i):
    i += 1; cls = False
    while i < len(src) and src[i] != "\n":
        c = src[i]
        if c == "\\": i += 2; continue
        if c == "[": cls = True
        elif c == "]": cls = False
        elif c == "/" and not cls: return i + 1
        i += 1
    return i


ATTR = re.compile(r'\b(?:title|placeholder|aria-label|alt|value|data-q)="([^"]*)"')
def html_strings(src: str):
    src = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    src = re.sub(r"<(script|style)\b.*?</\1>", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    out = []
    for ln, row in enumerate(src.split("\n"), 1):
        for m in ATTR.finditer(row):
            out.append((ln, m.group(1)))
        out.append((ln, re.sub(r"<[^>]*>", " ", row)))
    return out


def problems(text: str):
    if not CJK.search(text) and not EMOJI.search(text):
        return []
    vis = re.sub(r"<[^>]*>", " ", text)          # 模板里的 HTML 标签不算文字
    vis = re.sub(r"[a-zA-Z_$][\w$.]*\s*!==?|!\s*[a-zA-Z_$(]", " ", vis)   # 代码里的 ! / !==
    hits = []
    if "侧车" in vis: hits.append("侧车")
    for w in COLLOQ:
        if w in vis and not any(h in vis for h in ("一下子",) if w == "一下"):
            hits.append(w); break
    if "！" in vis: hits.append("！")
    if re.search(r"[\u4e00-\u9fff。，）」][ ]?!|![\u4e00-\u9fff]", vis): hits.append("!")
    if EMOJI.search(vis): hits.append("emoji")
    return hits


def scan(files):
    bad = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        items = html_strings(src) if f.suffix == ".html" else ts_strings(src)
        for ln, s in items:
            for h in problems(s):
                bad.append((f, ln, h, s.strip()[:60]))
    return bad


def selftest():
    assert [t for _, t in ts_strings('const e = s.replace(/[&<>"]/g, c => 1); const f = "侧车";')] == ["侧车"], "正则字面量"
    s = 'const a = "侧车未连接"; // 侧车 注释不算\nconst b = `点一下 ${x ? "好的！" : ""} ok`; if (!x) y();\n/* 搞 */ const c = "停车!";'
    got = [(ln, problems(t)) for ln, t in ts_strings(s) if problems(t)]
    want = [(1, ["侧车"]), (2, ["一下"]), (2, ["！"]), (3, ["!"])]
    assert got == want, got
    assert not problems("if (!ok) 显示「已连接」"), "代码里的 ! 不算"
    assert problems("完成🎉") == ["emoji"]
    h = html_strings('<button title="试一下">发送</button>\n<!-- 侧车 -->\n<p>本地服务已连接</p>')
    assert [p for _, t in h for p in problems(t)] == ["一下"], h
    print("check_copy selftest ok")


def main():
    if "--selftest" in sys.argv:
        selftest(); return 0
    files = [UI / "index.html"] + sorted(p for p in (UI / "src").rglob("*.ts"))
    bad = scan(files)
    for f, ln, h, s in bad:
        fix = FIX.get(h, "换成书面语（如「一下」删掉，「试一下」→「试运行」）")
        print(f"{f.relative_to(ROOT)}:{ln} · 命中「{h}」 · {s} · 处理：{fix}")
    print(f"check_copy: {len(files)} 个文件，{len(bad)} 处问题")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
