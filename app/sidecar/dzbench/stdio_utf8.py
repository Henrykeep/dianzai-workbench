"""#146：所有 CLI 出口统一输出 UTF-8，不看控制台代码页（Windows cp1252/cp936 下 print 中文会 UnicodeEncodeError）。"""
import sys


def ensure() -> None:
    for s in (sys.stdout, sys.stderr):
        if s is not None and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):     # 已关闭 / 不支持：保持原样
                pass
