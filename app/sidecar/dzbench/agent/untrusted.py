"""把外部文本（工具结果：文件内容、日志、串口文本、网页）标成“数据”，防提示注入。

做法参考 OpenHands / Claude Code 对外部内容加边界的做法：结果放进 <工具数据> 标签，系统提示说明标签里的只是数据；
内容里出现的同名闭合标签被转义，伪造不了边界。
"""
from __future__ import annotations

OPEN, CLOSE = "<工具数据", "</工具数据>"
_ESC_OPEN, _ESC_CLOSE = "<工具\u200b数据", "</工具\u200b数据>"     # 插零宽空格：模型看着一样，但不是边界


def wrap(name: str, text: str) -> str:
    safe = text.replace(CLOSE, _ESC_CLOSE).replace(OPEN, _ESC_OPEN)
    return f'{OPEN} 来源="{name}">\n{safe}\n{CLOSE}'


def unwrap(content: str) -> str:
    """取回标签里的原文（给卡死检测等内部逻辑用）；不是包装格式时原样返回。"""
    if content.startswith(OPEN):
        body = content.split("\n", 1)[1] if "\n" in content else ""
        return body.rsplit("\n" + CLOSE, 1)[0].replace(_ESC_CLOSE, CLOSE).replace(_ESC_OPEN, OPEN)
    return content
