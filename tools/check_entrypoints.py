#!/usr/bin/env python3
"""入口规则表检查（docs/dev/entrypoints.yaml）：每个用户动作恰好一个入口，侧车 op 无孤儿。

失败条件：动作 id / 标签 / 界面元素重复；at 不是已登记的步/工具箱类/常驻件；界面元素在 index.html 找不到；
op 被两个动作认领又没写进 shared_ops；侧车 op 既没界面动作也不在 script_ops；界面调用的 op 没登记；
登记的 op 侧车不认；Agent 工具没归属或归属两处；script_ops/shared_ops 里有已不存在的 op。
--selftest 用内置坏例子确认每条规则真的会失败。"""
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app"


VOID = {"input", "br", "hr", "img", "meta", "link", "source", "wbr"}
# 共用区域在哪些步可见（与 app/ui/src/steps.ts LAYOUT 一致）
SHARED_AREAS = {"dock": {"模块", "调参"}, "side": {"模块", "联调", "调参", "评分"}, "scope": {"模块", "联调", "调参", "评分"}}


def regions(html):
    """元素 id → 所在区域：page:<步> / toolbox / trouble / header / footer / dialog / dock / side / scope。"""
    from html.parser import HTMLParser
    out, stack = {}, []

    def where():
        for tag, a in reversed(stack):
            if a.get("data-page"):
                return "page:" + a["data-page"]
            if a.get("id") == "toolbox-m":
                return "toolbox"
            if a.get("id") == "trouble-m":
                return "trouble"
            if tag == "dialog":
                return "dialog"
            cls = (a.get("class") or "").split()
            for k in ("dock", "side", "scope"):
                if k in cls:
                    return k
            if tag in ("header", "footer"):
                return tag
        return "?"

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag not in VOID:
                stack.append((tag, a))
            if a.get("id"):
                out[a["id"]] = where() if tag not in VOID else (stack.append((tag, a)), where(), stack.pop())[1]

        def handle_endtag(self, tag):
            if any(t == tag for t, _ in stack):      # 不配对的结束标签忽略
                while stack and stack.pop()[0] != tag:
                    pass
    P().feed(html)
    return out


def placed(at, region):
    """at 与元素实际所在区域是否一致。"""
    kind, _, name = at.partition(":")
    if region == "dialog":
        return True                       # 对话框里的按钮跟着打开它的入口走
    if kind == "toolbox":
        return region == "toolbox"
    if kind == "always":
        return region == "trouble" if name == "排障" else region in ("header", "footer")
    if region.startswith("page:"):
        return region == "page:" + name
    return name in SHARED_AREAS.get(region, set())


def load_sources():
    ui_src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((APP / "ui/src").glob("*.ts")))
    html = (APP / "ui/index.html").read_text(encoding="utf-8")
    server = (APP / "sidecar/dzbench/server.py").read_text(encoding="utf-8")
    loop = (APP / "sidecar/dzbench/agent/loop.py").read_text(encoding="utf-8")
    tools_blk = loop.split("TOOLS = [", 1)[1] if "TOOLS = [" in loop else ""
    return {
        "server_ops": set(re.findall(r'op == "([a-z_0-9.]+)"', server)),
        "ui_ops": set(re.findall(r'(?:rpc|call|fire)(?:<[^>]*>)?\(\s*"([a-z_0-9.]+)"', ui_src)),
        "html_ids": set(re.findall(r'\bid="([^"]+)"', html)),
        "regions": regions(html),
        "agent_tools": set(re.findall(r'"name":\s*"([a-z_0-9]+)"', tools_blk)),
    }


def check(spec, src):
    err = []
    places = {f"step:{s}" for s in spec["steps"]} | {f"toolbox:{t}" for t in spec["toolbox"]} | {f"always:{a}" for a in spec["always"]}
    shared, script = spec.get("shared_ops") or {}, spec.get("script_ops") or {}
    seen = {"id": {}, "label": {}, "ui": {}}
    claim = {}
    for a in spec["actions"]:
        for k in ("id", "label", "ui"):
            v = a.get(k)
            if v in seen[k]:
                err.append(f"重复入口：{k}={v!r} 同时出现在 {seen[k][v]} 和 {a['id']}")
            seen[k][v] = a["id"]
        if "ready" in a and not isinstance(a["ready"], bool):
            err.append(f"{a['id']}: ready 只能是 true / false，收到 {a['ready']!r}")
        if a.get("at") not in places:
            err.append(f"{a['id']}: at={a.get('at')!r} 不是已登记的步 / 工具箱类 / 常驻件")
        if not a.get("dynamic") and a.get("ui") not in src["html_ids"]:
            err.append(f"{a['id']}: 界面元素 #{a.get('ui')} 在 index.html 里找不到")
        elif not a.get("dynamic") and "regions" in src and not placed(a.get("at", ""), src["regions"].get(a["ui"], "?")):
            err.append(f"{a['id']}: 表里写在 {a.get('at')}，界面上 #{a['ui']} 却在 {src['regions'].get(a['ui'], '?')}")
        for op in a.get("ops") or []:
            if op not in src["server_ops"]:
                err.append(f"{a['id']}: op {op} 侧车不认")
            if op in claim and claim[op] != a["id"] and op not in shared:
                err.append(f"重复入口：op {op} 被 {claim[op]} 和 {a['id']} 都认领（真共用就写进 shared_ops 并说明）")
            claim.setdefault(op, a["id"])
    for op in sorted(src["server_ops"] - set(claim) - set(script)):
        err.append(f"孤儿 op：{op} 没有界面动作也不在 script_ops")
    for op in sorted(src["ui_ops"] - set(claim)):
        err.append(f"界面调用了 {op} 但入口表没登记")
    for op in sorted((set(script) | set(shared)) - src["server_ops"]):
        err.append(f"script_ops/shared_ops 里的 {op} 侧车已没有")
    for op in sorted(set(script) & set(claim)):
        err.append(f"{op} 已有界面动作，从 script_ops 删掉")
    owner = {}
    for at, names in (spec.get("agent_tools") or {}).items():
        if at not in places:
            err.append(f"agent_tools: {at} 不是已登记的位置")
        for n in names:
            if n in owner:
                err.append(f"Agent 工具 {n} 归属两处：{owner[n]} / {at}")
            owner[n] = at
    for n in sorted(src["agent_tools"] - set(owner)):
        err.append(f"Agent 工具 {n} 没写归属步")
    for n in sorted(set(owner) - src["agent_tools"]):
        err.append(f"agent_tools 里的 {n} 已不是 Agent 工具")
    return err


def selftest():
    src = {"server_ops": {"a", "b", "c"}, "ui_ops": {"a", "z"}, "html_ids": {"x", "y"}, "agent_tools": {"t1", "t2"}}
    base = {"steps": ["调参"], "toolbox": ["记录"], "always": ["急停"], "shared_ops": {}, "script_ops": {"c": "脚本"},
            "agent_tools": {"step:调参": ["t1", "t2"]},
            "actions": [{"id": "A", "label": "甲", "at": "step:调参", "ui": "x", "ops": ["a"]},
                        {"id": "B", "label": "乙", "at": "toolbox:记录", "ui": "y", "ops": ["b"]}]}
    import copy
    ok = [e for e in check(base, src) if "z" not in e]
    assert not ok, ok
    cases = [
        ("label", lambda s: s["actions"][1].update(label="甲"), "重复入口：label"),
        ("ui", lambda s: s["actions"][1].update(ui="x"), "重复入口：ui"),
        ("op", lambda s: s["actions"][1]["ops"].append("a"), "重复入口：op a"),
        ("orphan", lambda s: s["actions"][1].update(ops=[]), "孤儿 op：b"),
        ("at", lambda s: s["actions"][0].update(at="step:不存在"), "不是已登记"),
        ("html", lambda s: s["actions"][0].update(ui="nope"), "找不到"),
        ("tool", lambda s: s["agent_tools"]["step:调参"].remove("t2"), "t2 没写归属"),
        ("script", lambda s: s["script_ops"].update(gone="x"), "gone 侧车已没有"),
        ("ready", lambda s: s["actions"][0].update(ready="no"), "ready 只能是"),
    ]
    for name, mut, want in cases:
        s = copy.deepcopy(base)
        mut(s)
        e = check(s, src)
        assert any(want in x for x in e), (name, e)
    assert any("界面调用了 z" in x for x in check(base, src))
    reg = regions('<header><button id="h"></button><details id="toolbox-m"><button id="t"></button></details></header>'
                  '<main class="work"><section data-page="烧录"><button id="f"></button></section><section class="scope"><input id="i"></section></main>')
    assert reg == {"h": "header", "toolbox-m": "toolbox", "t": "toolbox", "f": "page:烧录", "i": "scope"}, reg
    assert placed("step:烧录", "page:烧录") and not placed("step:封箱", "page:烧录")
    assert placed("toolbox:记录", "toolbox") and not placed("toolbox:记录", "header")
    assert placed("always:急停", "header") and not placed("always:急停", "dock") and placed("step:调参", "dock") and not placed("step:烧录", "dock")
    print(f"check_entrypoints selftest: {len(cases) + 6} ok")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return 0
    spec = yaml.safe_load((ROOT / "docs/dev/entrypoints.yaml").read_text(encoding="utf-8"))
    err = check(spec, load_sources())
    for e in err:
        print("✗", e)
    if err:
        print(f"入口规则表：{len(err)} 处不一致（docs/dev/entrypoints.yaml）")
        return 1
    print(f"✓ 入口规则表：{len(spec['actions'])} 个动作，op 无孤儿、无重复入口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
