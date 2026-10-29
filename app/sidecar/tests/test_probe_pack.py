"""MSPM0 器件包查找 + 传给 pyOCD；探针采样按相邻变量合并块读。"""
import os
import struct
import sys

import pytest

from dzbench import flash
from dzbench.elfsym import MockProbe, spans

HERE = os.path.dirname(__file__)


def test_find_pack_env_and_non_mspm0(tmp_path, monkeypatch):
    p = tmp_path / flash.M0_PACK
    p.write_bytes(b"PK")
    monkeypatch.setenv("DZBENCH_PACK", str(p))
    assert flash.find_pack("mspm0g3507") == p
    assert flash.find_pack("stm32f103c8") is None


def test_pack_passed_to_pyocd_or_clear_error(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(os.path.join(HERE, "fakepyocd"))
    for m in [k for k in sys.modules if k == "pyocd" or k.startswith("pyocd.")]:
        monkeypatch.delitem(sys.modules, m)
    import pyocd
    monkeypatch.setattr(pyocd, "BOARD", object(), raising=False)
    monkeypatch.setattr(pyocd, "LOG", [], raising=False)
    p = tmp_path / flash.M0_PACK
    p.write_bytes(b"PK")
    monkeypatch.setenv("DZBENCH_PACK", str(p))
    flash.PyOCDBackend("mspm0g3507")
    assert ("pack", str(p)) in pyocd.LOG
    monkeypatch.setattr(flash, "find_pack", lambda t: None)
    with pytest.raises(flash.FlashError) as e:
        flash.PyOCDBackend("mspm0g3507")
    assert e.value.code == "no_pack"


def test_sample_batches_adjacent_reads():
    items = [("a", 0x20000000, "f32"), ("b", 0x20000004, "i16"), ("c", 0x20000100, "u8"), ("d", 0x20000030, "f32")]
    sp = spans(items)
    assert [(hex(a), b - a, [m[0] for m in ms]) for a, b, ms in sp] == [("0x20000000", 0x34, ["a", "b", "d"]), ("0x20000100", 1, ["c"])]
    from dzbench.elfsym import SymbolWatch
    mem = bytearray(0x200)
    mem[0:4] = struct.pack("<f", 1.5)
    mem[4:6] = struct.pack("<h", -7)
    mem[0x30:0x34] = struct.pack("<f", 2.5)
    mem[0x100] = 9
    pr = MockProbe({0x20000000: bytes(mem)})
    reads = []
    orig = pr.read
    pr.read = lambda a, n: reads.append((a, n)) or orig(a, n)
    s = SymbolWatch.__new__(SymbolWatch)
    s.probe, s.items = pr, items
    assert s.sample() == {"a": 1.5, "b": -7.0, "c": 9.0, "d": 2.5} and len(reads) == 2
