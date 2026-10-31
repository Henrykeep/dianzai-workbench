"""r10 阻塞项：两块板来回插，同一 schema 哈希在本机对应两份内容不同的 link_schema.json（wd_timeout_ms 不同）。
侧车不挑第一份、也不挑最新的一份：报 schema_conflict（message_zh + fix_action），挡住显示和依赖 schema 的写入；
冲突解除（多余那份删掉）后重新连接恢复正常。走真仿真板会话（sim:car_2wd），不替身。"""
import json
import time

import pytest

from dzbench import progress as PG
from dzbench.session import LinkError, Session

pytestmark = pytest.mark.needs_sim


def _wait(cond, t=20.0):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < t:
        time.sleep(0.05)
    return cond()


def test_two_boards_same_hash_different_content_is_blocked(home, tmp_path, monkeypatch):
    extra = tmp_path / "schemas"
    monkeypatch.setenv("DZBENCH_SCHEMA_DIRS", str(extra))
    ev = []
    s = Session()
    s.emit = ev.append
    # 板 A：本机只有一份 → 正常
    s.connect("sim:car_2wd")
    try:
        assert _wait(lambda: s.schema is not None and len(s.params) == len(s.schema.params))
        a = s.schema
        assert s.schema_conflict is None and s.status()["schema_conflict"] is None
    finally:
        s.disconnect()
    # 板 B：同一应用编给另一块板，哈希相同、wd_timeout_ms 不同（另一块板的格式文件也在本机）
    d = json.loads(open(a.path, encoding="utf-8").read())
    d["wd_timeout_ms"] = int(a.wd_timeout_ms or 1000) + 700
    b = extra / "other-board" / "car_2wd" / "linkgen" / "link_schema.json"
    b.parent.mkdir(parents=True)
    b.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    ev.clear()
    s2 = Session()
    s2.emit = ev.append
    s2.connect("sim:car_2wd")
    try:
        assert _wait(lambda: s2.schema_conflict is not None)
        time.sleep(0.6)                                        # 多收几帧遥测：冲突时不解码、不出 schema 事件
        assert s2.schema is None and not s2.samples
        err = next(e for e in ev if e.get("code") == "schema_conflict")
        assert err["fix_action"] == "build" and err["message_zh"] and sorted(err["paths"]) == sorted([a.path, str(b)])
        assert not any(e.get("type") == "schema" for e in ev)
        st = s2.status()
        assert st["schema_ok"] is False and st["schema_conflict"]["reason"] == "schema_conflict"
        # 写入一律挡住
        for f in (lambda: s2.set_param("kp", 0.08), lambda: s2.read_param("kp"),
                  lambda: s2.step_start(0, 0, 3.0, 1000), lambda: s2.send_data(1, b"\0" * 8)):
            with pytest.raises(LinkError) as ei:
                f()
            assert ei.value.code == "schema_conflict" and ei.value.fix_action == "build"
        # 进度阻塞项
        snap = PG.derive(PG.collect(s2))
        bl = next(x for x in snap["blockers"] if x["code"] == "schema_conflict")
        assert bl["fix_action"] == "build" and bl["message_zh"] and "tune" in bl["blocks"]
        # 冲突解除：删掉不属于这块板的那份 → 重新连接恢复
        b.unlink()
        s2.disconnect()
        s2.connect("sim:car_2wd")
        assert _wait(lambda: s2.schema is not None and len(s2.params) == len(s2.schema.params))
        assert s2.schema_conflict is None
    finally:
        s2.disconnect()
