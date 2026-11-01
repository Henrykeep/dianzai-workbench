"""r10 阻塞项：两块板来回插，同一 schema 哈希在本机对应两份内容不同的 link_schema.json（wd_timeout_ms 不同）。
侧车不挑第一份、也不挑最新的一份：报 schema_conflict（message_zh + fix_action），挡住显示和依赖 schema 的写入；
冲突解除（多余那份删掉）后重新连接恢复正常。走真仿真板会话（sim:car_2wd），不替身。"""
import json
import pathlib
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
    from dzbench import schema as SC
    b = SC.cache_dir() / "other-board" / "car_2wd" / "link_schema.json"   # 另一块板的格式缓存拷贝（kind=cache）
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
        assert err["fix_action"] == "clear_schema_cache" and err["message_zh"] and err["reason"] == "schema_conflict"
        assert sorted(f["path"] for f in err["files"]) == sorted(str(pathlib.Path(x).resolve()) for x in (a.path, b))
        kinds = {f["path"]: f["kind"] for f in err["files"]}
        assert kinds[str(b.resolve())] == "cache" and kinds[str(pathlib.Path(a.path).resolve())] == "build"
        assert err["hash"] == f"{a.hash:08X}" and "board_uid" in err
        assert not any(e.get("type") == "schema" for e in ev)
        st = s2.status()
        assert st["schema_ok"] is False and st["schema_conflict"]["reason"] == "schema_conflict"
        # 写入一律挡住
        for f in (lambda: s2.set_param("kp", 0.08), lambda: s2.read_param("kp"),
                  lambda: s2.step_start(0, 0, 3.0, 1000), lambda: s2.send_data(1, b"\0" * 8)):
            with pytest.raises(LinkError) as ei:
                f()
            assert ei.value.code == "schema_conflict" and ei.value.fix_action == "clear_schema_cache"
        # 进度阻塞项
        snap = PG.derive(PG.collect(s2))
        bl = next(x for x in snap["blockers"] if x["code"] == "schema_conflict")
        assert bl["fix_action"] == "clear_schema_cache" and bl["message_zh"] and "tune" in bl["blocks"]
        assert bl["reason"] == "schema_conflict" and bl["hash"] == f"{a.hash:08X}" and len(bl["files"]) == 2 and "board_uid" in bl
        # 冲突解除：删掉不属于这块板的那份 → 重新连接恢复
        b.unlink()
        s2.disconnect()
        s2.connect("sim:car_2wd")
        assert _wait(lambda: s2.schema is not None and len(s2.params) == len(s2.schema.params))
        assert s2.schema_conflict is None
    finally:
        s2.disconnect()


def test_clear_schema_cache_removes_only_that_hash_and_rehandshakes(home, tmp_path, monkeypatch):
    """op clear_schema_cache {hash}：只删这个哈希的缓存格式文件（别的哈希不碰），返回 {ok, removed}，然后重新识别。
    搜索目录限定在临时目录（不动仓库 build/）；同哈希的编译产物不删，清完立即能用。"""
    from dzbench import schema as SC
    cache = SC.cache_dir()
    build = tmp_path / "proj" / "build"                       # 编译产物：同哈希，clear_schema_cache 绝不能删
    monkeypatch.setattr(SC, "search_dirs", lambda: [build, cache])
    real = None
    for d in SC.__dict__["ROOT"].joinpath("build").rglob("link_schema.json"):
        if "host-sim/car_2wd" in d.as_posix():
            real = json.loads(d.read_text("utf-8"))
    assert real, "先 make 出 host-sim car_2wd"
    fa = cache / "board-a" / "link_schema.json"
    fb = cache / "board-b" / "link_schema.json"
    fo = cache / "other" / "link_schema.json"
    fbuild = build / "host-sim" / "car_2wd" / "link_schema.json"
    for f, d in ((fbuild, real), (fa, real), (fb, dict(real, wd_timeout_ms=int(real.get("wd_timeout_ms") or 1000) + 700)),
                 (fo, dict(real, hash=(int(real["hash"]) ^ 0x1) & 0xFFFFFFFF))):
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    ev = []
    s = Session()
    s.emit = ev.append
    s.connect("sim:car_2wd")
    try:
        assert _wait(lambda: s.schema_conflict is not None)
        ev.clear()
        r = s.clear_schema_cache(int(real["hash"]))
        assert r["ok"] and sorted(r["removed"]) == sorted(str(f.resolve()) for f in (fa, fb))
        assert fo.exists() and not fa.exists() and not fb.exists()               # 别的哈希不碰
        assert fbuild.exists()                                                   # 编译产物留着（前端报的 4057a9b 回归）
        assert any(e.get("type") == "rehandshake" for e in ev)
        assert s.schema_conflict is None
        # 重新识别：编译产物还在 → 直接恢复，不用重新编译
        s.disconnect()
        s.connect("sim:car_2wd")
        assert _wait(lambda: s.schema is not None) and s.schema_conflict is None
    finally:
        s.disconnect()


def test_conflict_only_build_outputs_fix_is_rebuild(home, tmp_path):
    """冲突两份都是编译产物（或编译产物对板子 'I' 回包）：fix_action = build（重编重烧），不是 clear_schema_cache；files 带 kind。"""
    from dzbench import schema as SC
    e = SC.SchemaConflict(0x1234, [str(tmp_path / "a" / "link_schema.json"), str(SC.cache_dir() / "x" / "link_schema.json")])
    assert e.fix_action == "clear_schema_cache" and [f["kind"] for f in e.as_dict()["files"]] == ["build", "cache"]
    e = SC.SchemaConflict(0x1234, [str(tmp_path / "build" / "link_schema.json")], message_zh="I 回包不一致")
    assert e.fix_action == "build" and e.as_dict()["files"][0]["kind"] == "build" and e.as_dict()["fix_action"] == "build"
