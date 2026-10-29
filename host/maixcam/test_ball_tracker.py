"""钢珠跟踪器：干扰色块、漏检外推、丢失后重捕获。"""
import os
import random
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ball_tracker import BallTracker, Blob  # noqa: E402

random.seed(1)
t = BallTracker()
# 球从左向右匀速 3 px/帧；右上角有一个更大的固定反光块；偶尔一个细长干扰（线缆）
xs = []
for k in range(60):
    bx = 60 + 3 * k
    blobs = [Blob(bx + random.uniform(-1, 1), 120, 10, 10, 80),
             Blob(300, 20, 30, 30, 600),            # 大反光：不能被它抢走
             Blob(bx + 25, 125, 40, 4, 160)]         # 细长：长宽比淘汰
    if k in (30, 31, 32):
        blobs = blobs[1:]                           # 漏检 3 帧
    r = t.update(blobs) if k > 2 else t.update([blobs[0]])
    if k < 2:
        assert not r.detected and r.x is None, (k, r)          # 锁定确认期（默认 3 帧）不输出
    elif k in (30, 31, 32):
        assert r.predicted and not r.detected, (k, r)
        assert abs(r.x - (bx - 160)) < 6, (k, r.x, bx - 160)   # 外推仍在球附近
    else:
        assert r.detected and abs(r.x - (bx - 160)) < 4, (k, r.x, bx - 160)
    xs.append(r.x)
roi = t.roi()
assert roi[2] < 320 and roi[0] > 100, roi                  # 跟踪中只搜小窗口
for _ in range(10):
    r = t.update([])
assert r.x is None and not r.predicted and t.roi() == [0, 0, 320, 240]   # 丢失 → 全画面
for _ in range(3):
    r = t.update([Blob(50, 50, 9, 9, 70)])
assert r.detected and abs(r.x + 110) < 1e-6                 # 重捕获（连续 3 帧确认）

# 单帧反光 / 跳来跳去的色块不会被锁定
t = BallTracker()
for k in range(6):
    r = t.update([Blob(40 + 90 * (k % 3), 60, 10, 10, 80)])
    assert not r.detected, (k, r)
# confirm=1 恢复旧行为：第一帧即锁定
assert BallTracker(confirm=1).update([Blob(10, 10, 9, 9, 70)]).detected

# 外推速度逐帧衰减：快球丢失后外推位移有界
t = BallTracker()
for k in range(10):
    t.update([Blob(20 + 10 * k, 120, 10, 10, 80)])
x0 = t.x
for _ in range(4):
    r = t.update([])
assert r.predicted and t.x - x0 < 10 * 4 * 0.9, (t.x - x0)  # 不衰减会是 40 px
# 快球（15 px/帧，门限 20）持续跟住
t = BallTracker(gate_px=20)
for k in range(10):
    r = t.update([Blob(20 + 15 * k, 120, 10, 10, 80)])
assert r.detected and abs(r.x - (20 + 15 * 9 - 160)) < 4

print("ball_tracker 自测通过")
