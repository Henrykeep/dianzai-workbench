"""链路心跳条：每秒格子的 fps / CRC / 丢帧计数，与 dzlog 时间对齐。"""
import time

import pytest

from dzbench.linkhealth import LinkHealth


def test_cells_fps_crc_drops():
    h = LinkHealth()
    assert h.tick(0.0, 0, 0, 0, 0.0, 0.0) == []           # 第一次只开格
    for s in (0, 1, 2, 5, 6):                              # 3、4 丢了
        h.on_frame(s)
    assert h.tick(0.5, 3, 0, 100, 0.5, 0.5) == []          # 不满 1 s 不收
    (c,) = h.tick(1.0, 50, 2, 1000, 12.34, 3.2)
    assert c["fps"] == 50 and c["crc"] == 2 and c["drops"] == 2 and c["bytes"] == 1000
    assert c["log_t"] == 12.34 and c["plot_t"] == 3.2 and c["i"] == 0
    (c,) = h.tick(2.0, 80, 2, 1500, None, None)
    assert c["fps"] == 30 and c["crc"] == 0 and c["drops"] == 0 and c["log_t"] is None and c["i"] == 1
    assert len(h.history()) == 2


def test_seq_wrap_and_reset_not_drops():
    h = LinkHealth()
    h.tick(0.0, 0, 0, 0, None, None)
    for s in (254, 255, 0, 1):                             # 8 位回绕不是丢帧
        h.on_frame(s)
    h.on_frame(100)                                        # 跳 98：当作丢 98
    h.on_frame(10)                                         # 倒退（缺口 ≥128）= 板子复位，不计
    (c,) = h.tick(1.0, 0, 0, 0, None, None)
    assert c["drops"] == 98


def test_rebase_keeps_history():
    h = LinkHealth()
    h.tick(0.0, 0, 0, 0, None, None)
    h.tick(1.0, 10, 0, 0, None, None)
    h.on_frame(7)
    h.rebase()                                             # 回放跳转：解析器清零
    h.on_frame(200)
    assert h.tick(1.2, 0, 0, 0, None, None) == []          # 重新开格，不出负数
    (c,) = h.tick(2.2, 5, 0, 0, None, None)
    assert c["drops"] == 0 and c["fps"] == 5 and len(h.history()) == 2


@pytest.mark.needs_sim
def test_sim_session_emits_cells(home):
    from dzbench.session import Session
    s = Session()
    s.connect("sim:car_2wd")
    try:
        cells = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < 4 and len(cells) < 2:
            cells += s.status().get("hb", [])
            time.sleep(0.1)
        assert len(cells) >= 2
        c = cells[-1]
        assert c["fps"] > 5 and c["crc"] == 0 and c["drops"] == 0
        assert c["log_t"] is not None and c["log_t"] > 0.5      # 默认在记录：格子带 dzlog 时间
        assert c["plot_t"] is not None
    finally:
        s.disconnect()
