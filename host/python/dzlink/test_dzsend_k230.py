"""PC 上核对 host/k230/dzsend.py（MicroPython 单文件）与 dzlink 逐字节一致。"""
import importlib.util
import os

from .protocol import encode, pack_fields

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("dzsend", os.path.join(HERE, "..", "..", "k230", "dzsend.py"))
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)


def main():
    out = []
    tx = K.DzSend(out.append)
    tx.send(1, [("u8", 9), ("i16", -40000), ("u32", 77), ("f32", 0.25)])
    tx.heartbeat()
    f = [{"name": "a", "type": "u8"}, {"name": "b", "type": "i16"}, {"name": "c", "type": "u32"}, {"name": "d", "type": "f32"}]
    assert out[0] == encode(0, 1, 0, pack_fields(f, {"a": 9, "b": -32768, "c": 77, "d": 0.25}))
    assert out[1] == encode(3, 0, 1, b"")
    for n in range(0, 65, 16):
        assert K.encode(0, 5, n, bytes(range(n))) == encode(0, 5, n, bytes(range(n)))
    print("k230 dzsend 自测通过")


if __name__ == "__main__":
    main()
