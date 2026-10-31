"""estop_latch.json：侧车重启后心跳再报一次急停，不得把 t / latched_at 改写成重启时刻；只补缺字段，只有 clear() 重置。"""
import json
import time

from dzbench import latch, snapshots


def test_restart_keeps_original_latch_time(home):
    latch.set("COM7", None, "firmware:hb_timeout", "心跳超时", {"cause": "hb_timeout", "message_zh": "心跳超时 1600 ms"})
    p = snapshots.base_dir() / "estop_latch.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    t0 = time.time() - 3 * 3600                             # 把原始锁存时刻挪到 3 小时前，模拟侧车重启隔了很久
    la0 = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))
    for r in d.values():
        r["t"], r["latched_at"] = t0, la0
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    hm0 = time.strftime("%H:%M", time.localtime(t0))
    # 侧车重启：再次心跳急停，带上新测到的字段
    latch.set("COM7", None, "firmware:hb_timeout", "心跳超时",
              {"cause": "hb_timeout", "measured_ms": 1600, "threshold_ms": 1500})
    rec = latch.get("COM7", None)
    assert rec["t"] == t0 and rec["latched_at"] == la0, rec
    assert rec["measured_ms"] == 1600 and rec["threshold_ms"] == 1500, rec
    assert latch.restored_view(rec)["message_zh"].startswith(hm0), rec
    latch.clear("COM7", None)
    latch.set("COM7", None, "manual", "手动急停")
    assert latch.get("COM7", None)["t"] > t0 + 3600
