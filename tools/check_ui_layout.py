#!/usr/bin/env python3
"""界面布局门禁（docs/dev/ui-layout-rules.md §7）：
1. 颜色只用设计变量：app/ui/src 下除 tokens.css 外的 .css 不许出现 #hex / rgb() / hsl() / oklch() 字面量；
2. 每个区域顶层可见按钮 ≤ 上限：按钮在 <details>（更多 / 工具箱 / 排障 / 回到…）或 <dialog> 里不算。
用法：python3 tools/check_ui_layout.py [--selftest]"""
import pathlib, re, sys
from html.parser import HTMLParser
ROOT = pathlib.Path(__file__).resolve().parents[1]
UI = ROOT / "app/ui"
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab)\(")
# 区域（按元素 id / class 定位）→ 顶层可见按钮上限
# 内层区域写在前面先匹配：steps = 时间线步骤栏（不计）；raw = 模块页收发子视图；dk = 左栏单个标签页；commit = 撤销/下发
LIMITS = {"steps": 99, "raw": 4, "commit": 2, "dk": 2, "tunebar": 3, "agent": 2, "scope": 2, "dock": 1, "top": 6}


def color_errs(files):
    err = []
    for f, text in files:
        for i, line in enumerate(text.splitlines(), 1):
            code = re.sub(r"/\*.*?\*/", "", line)
            if COLOR.search(code):
                err.append(f"{f}:{i}: 颜色字面量，改用 tokens.css 变量")
    return err


def button_counts(html):
    counts = {k: 0 for k in LIMITS}
    stack = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "button" or (tag == "summary"):
                hidden = any(t in ("details", "dialog") for t, _ in stack)
                if tag == "summary":
                    hidden = sum(t == "details" for t, _ in stack) > 1 or any(t == "dialog" for t, _ in stack)
                if not hidden:
                    for t, x in reversed(stack):
                        cls = (x.get("class") or "").split()
                        k = next((k for k in cls if k in LIMITS), None)
                        if k:
                            counts[k] += 1
                            break
            if tag not in ("input", "br", "hr", "img", "meta", "link"):
                stack.append((tag, a))

        def handle_endtag(self, tag):
            if any(t == tag for t, _ in stack):
                while stack and stack.pop()[0] != tag:
                    pass
    P().feed(html)
    return counts


def check(html, css_files):
    err = color_errs(css_files)
    for k, n in button_counts(html).items():
        if n > LIMITS[k]:
            err.append(f"区域 .{k} 顶层可见按钮 {n} 个 > 上限 {LIMITS[k]}：次要的收进「更多」或工具箱")
    return err


def selftest():
    good = '<header class="top"><nav class="steps">' + "<button>s</button>" * 8 + '</nav><button>a</button><details><summary>m</summary><button>b</button><button>c</button></details></header>'
    assert not check(good, [("x.css", "a{color:var(--ink)}")])
    assert check("", [("x.css", "a{color:#fff}")])
    bad = '<section class="tunebar">' + "<button>x</button>" * 4 + "</section>"
    assert check(bad, [])
    print("✓ check_ui_layout selftest")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest(); sys.exit(0)
    css = [(p.relative_to(ROOT), p.read_text(encoding="utf-8")) for p in sorted((UI / "src").glob("*.css")) if p.name != "tokens.css"]
    e = check((UI / "index.html").read_text(encoding="utf-8"), css)
    for x in e:
        print("✗", x)
    if e:
        sys.exit(1)
    print(f"✓ check_ui_layout: 颜色只用变量；顶层按钮 {button_counts((UI / 'index.html').read_text(encoding='utf-8'))}")
