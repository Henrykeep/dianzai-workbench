#!/usr/bin/env python3
"""tools/report.py 的测试：用已知解析解的二阶系统生成"录像"，核对表里的数、要求判定、仿真/实物不能混标、SVG 合法。"""
import csv
import math
import pathlib
import random
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import report  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("✓ " if cond else "✗ ") + msg)
    fails += 0 if cond else 1


def second_order(zeta, wn, amp, noise, seed, t_end=3.0, dt=0.002, t_step=0.5):
    rnd = random.Random(seed)
    wd = wn * math.sqrt(1 - zeta ** 2)
    rows = []
    for k in range(int(t_end / dt)):
        t = k * dt
        sp = amp if t >= t_step else 0.0
        if t < t_step:
            y = 0.0
        else:
            tau = t - t_step
            y = amp * (1 - math.exp(-zeta * wn * tau) * (math.cos(wd * tau) + zeta / math.sqrt(1 - zeta ** 2) * math.sin(wd * tau)))
        rows.append((t, y + rnd.gauss(0, noise), sp, 0.3))
    return rows


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "ball_x[mm]", "ball_sp[mm]", "beam_cmd[deg]"])
        w.writerows(rows)


d = pathlib.Path(tempfile.mkdtemp())
zeta, wn = 0.5, 8.0
os_true = 100 * math.exp(-zeta * math.pi / math.sqrt(1 - zeta ** 2))   # 16.3%
files = []
for i in range(3):
    f = d / f"run{i+1}.csv"
    write(f, second_order(zeta, wn, 100.0, 0.2, i))
    files.append(str(f))
snap = d / "定稿.json"
snap.write_text('{"name":"定稿","time":"2026-10-29 16:00:00","note":"现场第3轮","values":{"ball_kp":1.2,"ball_kd":0.35}}', encoding="utf-8")

out = d / "out"
r = report.build(files, "ball_x", "ball_sp", source="board", params=str(snap),
                 reqs=report.parse_req(["overshoot<=20", "settling<=1.5"]), title="基本要求(2)", out=out)
check(r["valid"] == 3, "3 次都能算")
ov = [float(row[4]) for row in r["rows"]]
check(all(abs(v - os_true) < 1.0 for v in ov), f"超调量与解析解 {os_true:.1f}% 一致：{ov}")
check(all(row[-1] == "满足" for row in r["rows"]), "超调<=20、调节<=1.5 判满足")
r2 = report.build(files, "ball_x", "ball_sp", source="board", reqs=report.parse_req(["overshoot<=10"]), out=d / "o2")
check(all(row[-1].startswith("不满足（超调量<=10") for row in r2["rows"]), "超调<=10 判不满足并写明哪条")
check(any(s[0] == "满足率" and s[1] == "0/3" for s in r2["summary"]), "满足率 0/3")
md = (out / "results.md").read_text(encoding="utf-8")
check("| ball_kp | 1.2 |" in md and "现场第3轮" in md, "参数表来自快照，带时间和备注")
check("（待填" in md and "实物" in md, "测试条件 / 误差分析留给人填，不编")
for f in ["step.svg", "run_1.svg", "results.csv"]:
    check((out / f).exists(), f"生成 {f}")
for f in ["step.svg", "run_2.svg"]:
    try:
        ET.parse(out / f)
        check(True, f"{f} 是合法 XML")
    except ET.ParseError as e:
        check(False, f"{f} 解析失败 {e}")
with open(out / "results.csv", encoding="utf-8-sig") as fh:
    head = next(csv.reader(fh))
check(head[:3] == ["次", "文件", "数据来源"], "CSV 表头")

# 仿真必须标出来
r3 = report.build(files[:1], "ball_x", "ball_sp", source="sim", out=d / "o3")
check("仿真数据，不得写成实测" in (d / "o3" / "results.md").read_text(encoding="utf-8"), "仿真数据有醒目标注")
for bad, why in ((dict(source=""), "--source 缺失"), (dict(source="board", y="nope"), "列名不存在")):
    kw = dict(files=files[:1], y="ball_x", sp="ball_sp", out=d / "o4")
    kw.update(bad)
    try:
        report.build(**kw)
        check(False, f"{why} 应报错")
    except report.ReportError as e:
        check(True, f"{why} 报错：{e}")
try:
    report.parse_req(["超调<10"])
    check(False, "非法 --req 应报错")
except report.ReportError:
    check(True, "非法 --req 报错")

# 没有阶跃的录像：不崩，行里写原因
flat = d / "flat.csv"
write(flat, [(k * 0.01, 0.0, 0.0, 0.0) for k in range(100)])
r5 = report.build([str(flat)] + files[:1], "ball_x", "ball_sp", source="board", out=d / "o5")
check(r5["valid"] == 1 and r5["rows"][0][-1].startswith("无法计算"), "无阶跃的那次标'无法计算'，其余照算")

# 慢到没进误差带：调节时间写"未进带"，有要求时判不满足
slow = d / "slow.csv"
write(slow, second_order(0.9, 0.8, 100.0, 0.0, 9, t_end=2.0))
r6 = report.build([str(slow)], "ball_x", "ball_sp", source="board", reqs=report.parse_req(["settling<=1"]), out=d / "o6")
check(r6["rows"][0][5] == "未进带" and r6["rows"][0][-1].startswith("不满足"), "没进带 → '未进带'且不满足")

print(f"test_report: {'通过' if not fails else f'{fails} 项失败'}")
sys.exit(1 if fails else 0)
