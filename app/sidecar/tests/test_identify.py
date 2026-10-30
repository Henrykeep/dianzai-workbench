"""identify.py：原 GPL 实现删除后，诚实地报不可用（不跳过）。"""
import pytest

from dzbench.tuning import identify as I


def test_unavailable_is_honest():
    with pytest.raises(I.IdentError, match="暂不可用"):
        I.open_loop_pid([0, 1], [0, 1], 0.5, 1.0)
    r = I.steady_state([0, 1], [0, 1])
    assert r["steady"] is False and r["reason"] == "unavailable" and "GPL" in r["text"]
