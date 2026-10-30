#!/usr/bin/env python3
"""tools/req.py 的测试：两种题目写法起稿、核对规则、清单渲染、2026H 实例通过。"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import req  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

OLD = """参赛注意事项
（1）每队严格限制 3 人，不得中途更换队员。
一、任务
设计一个风力摆。
二、要求
1．基本要求
（1）摆杆从静止开始，15s 内控制摆动，
幅度不小于 50cm。（15 分）
（2）设置角度后 5s 内摆动，误差≤5°。（20 分）
2．发挥部分
（1）抗扰：恢复时间不超过 5s。（25 分）
三、说明
1. 只能使用一块主控板。不得使用商品化云台。
"""
NEW = """一、任务
设计一辆车。
二、要求
  1. 小车沿黑线一圈，总时间≤20s，停车偏差≤2cm。（16 分）
  2. 小车静止，误差绝对值≤1cm，要求运行时间≤5s。
（13 分）
三、说明
  5. 小车循迹模块只能使用红外光电模块。显示屏尺寸不大于 2 英
寸。
"""


def test_init_old_style():
    d = req.init_skeleton(OLD, "X", "t")
    ids = [(i["id"], i["part"], i.get("score")) for i in d["items"]]
    assert ids == [("B1", "basic", 15.0), ("B2", "basic", 20.0), ("A1", "advanced", 25.0)], ids
    assert d["items"][0]["text"].startswith("摆杆从静止开始，15s 内") and "幅度不小于 50cm" in d["items"][0]["text"]
    # init 现在抓全部数值；== 是设定值/工作条件（如“15s 内”），阈值另列
    thr = lambda i: [m for m in d["items"][i]["metrics"] if m["op"] != "=="]
    assert [(m["op"], m["value"], m["unit"]) for m in thr(0)] == [(">=", 50.0, "cm")]
    assert (15.0, "s") in [(m["value"], m["unit"]) for m in d["items"][0]["metrics"] if m["op"] == "=="]
    assert [(m["op"], m["value"]) for m in thr(2)] == [("<=", 5.0)]
    texts = [c["text"] for c in d["constraints"]]
    assert any("一块主控板" in t for t in texts) and any("商品化云台" in t for t in texts)
    assert not any("更换队员" in t for t in texts), "参赛注意事项不应进约束"


def test_init_new_style_multiline_score():
    d = req.init_skeleton(NEW, "X", "t")
    assert [(i["id"], i.get("score")) for i in d["items"]] == [("B1", 16.0), ("B2", 13.0)]
    assert [(m["value"], m["unit"]) for m in d["items"][0]["metrics"]] == [(20.0, "s"), (2.0, "cm")]
    assert "sense.line" in d["items"][0]["needs"] and "act.wheel_drive" in d["items"][0]["needs"], d["items"][0]["needs"]
    assert any("红外" in c["text"] for c in d["constraints"])
    assert any("不大于 2 英寸" in c["text"] for c in d["constraints"]), "跨行的“英 寸”要接上"



def test_real_pdf_if_present():
    """本机有原题 PDF 时（/workspace/nuedc，不进仓库）用真题跑一遍；CI 上跳过。"""
    pdf = pathlib.Path("/workspace/nuedc/H题_车载平衡滚球运动控制系统.pdf")
    if not pdf.exists():
        print("  跳过：没有原题 PDF"); return
    d = req.init_skeleton(req.read_text(pdf), "2026H", str(pdf))
    assert [i.get("score") for i in d["items"]] == [6, 16, 13, 20, 20, 20, 5, 20]
    t = " ".join(c["text"] for c in d["constraints"])
    for k in ("红外光电", "不大于 2 英寸", "封存", "增摩擦", "必须采用摄像头"):   # 往届复盘里“漏看”的几条
        assert k in t, k


def _write(tmp, text, proj=None):
    p = pathlib.Path(tmp) / "requirements.yaml"; p.write_text(text, encoding="utf-8")
    if proj:
        (pathlib.Path(tmp) / "project.yaml").write_text(proj, encoding="utf-8")
    return p


PROJ = """subsystems: [{name: a}, {name: b}]
link: {accept: [{name: 定位}]}
tests: [{id: 1}]
"""


def test_check_cross_refs():
    with tempfile.TemporaryDirectory() as t:
        p = _write(t, """schema_version: 1
problem: {code: X, title: t, source: s, project: project.yaml}
items:
  - {id: B1, part: basic, score: 5, text: x, subsystems: [a, zz, "ext:机械"], accept: 无此项, test_id: 9,
     metrics: [{name: e, op: "<=", value: 1}]}
  - {id: B1, part: advanced, text: y}
""", PROJ)
        err, warn = req.check(req.load(p), p.parent)
        joined = "\n".join(err)
        assert "编号重复：B1" in joined and "zz" in joined and "无此项" in joined and "test_id=9" in joined
        assert "以 A 开头" in joined and "ext:机械" not in joined, err
        assert any("不可验收" in w for w in warn) and any("签字" in w for w in warn)


def test_2026h_example_consistent_and_renders():
    p = ROOT / "examples/2026H_ball/requirements.yaml"
    d = req.load(p)
    err, _ = req.check(d, p.parent)
    assert not err, err
    md, rows = req.render(d)
    assert sum(i.get("score", 0) for i in d["items"]) == 120          # 100 分实物 + 20 分报告
    assert "| B4 | 20 | ● | ● |" in md and "sense.line_camera" in md
    assert len(rows) == 1 + len(d["items"])
    assert md.index("| B4 |") < md.index("| B3 |"), "同一部分内按分值降序"


def test_evidence_rules_and_table():
    with tempfile.TemporaryDirectory() as t:
        T = pathlib.Path(t)
        good = T / "logs/20261029-2140_taskB1_bench"; good.mkdir(parents=True); (good / "notes.md").write_text("x")
        empty = T / "logs/20261029-2141_taskB2_sim"; empty.mkdir(parents=True)
        p = _write(t, """schema_version: 1
problem: {code: X, title: t, source: s, project: project.yaml}
items:
  - {id: B1, part: basic, score: 5, text: x, subsystems: [a], accept: 定位, why: 串级,
     forbidden_claims: [仿真过了就行],
     evidence: [{path: logs/20261029-2140_taskB1_bench, layer: bench, date: "2026-10-29", result: pass},
                {path: logs/20261029-2140_taskB1_bench, layer: sim, date: "2026-10-28", result: pass}]}
  - {id: B2, part: basic, score: 5, text: y, subsystems: [b], accept: 定位,
     evidence: [{path: logs/20261029-2141_taskB2_sim, layer: sim, date: "2026-10-29", result: pass},
                {path: logs/nope, layer: sim, date: "2026-10-29", result: fail},
                {path: logs/20261029-2140_taskB1_bench, layer: bench, date: "2026-10-29", result: pass}]}
  - {id: B3, part: basic, score: 5, text: z, subsystems: [a], accept: 定位}
""", PROJ)
        d = req.load(p)
        err, warn = req.check_evidence(d, p.parent)
        j = "\n".join(err)
        assert "层" in j and "日期" in j, err                 # B1 第二条：layer/date 与目录名不符
        assert "nope" in j and "空" in j and "B1" in j, err   # 不存在、空目录、编号不符
        assert any("flash" in w for w in warn) and any("why" in w for w in warn), warn
        st = {i["id"]: req.status(i) for i in d["items"]}
        assert st["B1"] == "台架通过" and st["B3"] == "未测", st
        md = req.render_evidence(d)
        assert "仿真过了就行" in md and "“B1 已得分”" in md, "非现场通过自动禁止说已得分"


def test_init_metrics_and_needs():
    """init 抓全数值（范围/公差/比较/设定值，含无单位的比较）并按通用关键词表起草 needs。"""
    txt = "Uo=32V±0.1V、频率 fo=60±0.2Hz、Io 在 0.2A～2.0A 间变化，功率因数不低于 0.98，每项完成时间不超过 2 秒，小车显示距离"
    ms = req.extract_metrics(txt)
    got = [(m["op"], m["value"], m["unit"]) for m in ms]
    assert ("in", [31.9, 32.1], "V") in got and ("in", [59.8, 60.2], "Hz") in got, got
    assert ("in", [0.2, 2.0], "A") in got and (">=", 0.98, "") in got and ("<=", 2.0, "秒") in got, got
    nd = req.suggest_needs(txt, {"act.wheel_drive": ["小车"], "ui.display": ["显示"], "x.none": ["不存在的词"]})
    assert nd == ["act.wheel_drive", "ui.display"], nd
    kw = req.load_keywords()
    assert kw and all(isinstance(v, list) for v in kw.values()), "tools/catalog/needs_keywords.yaml 读不出来"


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("✓", k)
    print(f"test_req: {n} 项通过")
