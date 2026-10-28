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
    r = t.update(blobs) if k else t.update([blobs[0]])
    if k in (30, 31, 32):
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
r = t.update([Blob(50, 50, 9, 9, 70)])
assert r.detected and abs(r.x + 110) < 1e-6                 # 重捕获
print("ball_tracker 自测通过")
