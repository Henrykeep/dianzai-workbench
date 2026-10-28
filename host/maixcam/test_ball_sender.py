"""核对：内置通道定义 == board.yaml；发出的帧能被 dzlink.Link 按 board.yaml 解码；flags 语义。"""
import os
import sys
import yaml
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from ball_sender import BallSender, BALL_CH, F_VALID, F_DETECTED, F_PREDICTED  # noqa: E402
from dzlink.channels import Link  # noqa: E402
from dzlink.transport import LoopbackTransport  # noqa: E402

board = yaml.safe_load(open(os.path.join(HERE, "..", "..", "boards", "maixcam2-vision", "board.yaml"), encoding="utf-8"))
ch = next(c for c in board["coprocessor"]["channels"] if c["name"] == "ball")
assert ch["id"] == BALL_CH["id"] and [(f["name"], f["type"]) for f in ch["fields"]] == \
    [(f["name"], f["type"]) for f in BALL_CH["fields"]], "ball_sender.py 内置通道与 board.yaml 不一致"
t = LoopbackTransport()
link = Link(board, t)
s = BallSender(t.write)
s.send(-37.4, 123456)
s.send(None, 123496)
s.send(40000, 5, predicted=True)
t.buf[0:0] = b"\x00\xA5\x5A\x07"   # 帧前垃圾（含假帧头），解析器应重同步
got = link.poll()
assert [g[0] for g in got] == ["ball", "ball", "ball"], got
a, b, c = (g[1] for g in got)
assert a == {"flags": F_VALID | F_DETECTED, "x_px": -37, "cam_ms": 123456}, a
assert b["flags"] == 0 and b["x_px"] == 0, b
assert c["x_px"] == 32767 and c["flags"] == F_VALID | F_PREDICTED | F_DETECTED, c
print("ball_sender 自测通过")
