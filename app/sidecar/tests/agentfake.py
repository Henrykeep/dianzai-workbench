"""测试用的脚本化大模型：按顺序回放预设回复，并记下每次看到的消息。"""
import json


class FakeLLM:
    def __init__(self, script):
        self.script, self.seen = list(script), []

    def chat(self, messages, tools=None):
        self.seen.append((json.loads(json.dumps(messages)), tools))
        return self.script.pop(0)


def call(_tool, **args):
    return {"id": _tool, "type": "function", "function": {"name": _tool, "arguments": json.dumps(args)}}
