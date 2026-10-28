"""dzlink.sender / autodetect 自测：打包与 C 端一致的帧、截断、限速；平台识别；用假串口探测心跳。"""
import os
import tempfile

from .protocol import HEARTBEAT, Parser, encode, unpack_fields
from .sender import Sender
from .transport import LoopbackTransport
from . import autodetect as A

CH = {"ball": {"id": 1, "fields": [{"name": "flags", "type": "u8"}, {"name": "x_px", "type": "i16"},
                                   {"name": "cam_ms", "type": "u32"}]},
      "pose": {"id": 3, "fields": [{"name": "x", "type": "f32"}, {"name": "y", "type": "f32"}]}}


def main():
    lb = LoopbackTransport()
    t = [0.0]
    s = Sender(lb, CH, min_period_s=0.02, clock=lambda: t[0])
    assert s.send("ball", flags=1, x_px=99999, cam_ms=5)        # 99999 截断到 32767
    assert not s.send("ball", flags=1, x_px=1, cam_ms=6)         # 限速
    t[0] = 0.05
    assert s.send("pose", x=1.5, y=-2.0)
    fr = Parser().feed(lb.read())
    assert len(fr) == 2 and fr[0][1] == 1 and fr[1][1] == 3
    assert unpack_fields(CH["ball"]["fields"], fr[0][3]) == {"flags": 1, "x_px": 32767, "cam_ms": 5}
    assert unpack_fields(CH["pose"]["fields"], fr[1][3]) == {"x": 1.5, "y": -2.0}
    assert fr[0][2] == 0 and fr[1][2] == 1 and s.dropped == 1
    try:
        Sender(lb, {"big": {"id": 9, "fields": [{"name": "a%d" % i, "type": "f32"} for i in range(17)]}})
        raise AssertionError("超长通道应报错")
    except ValueError:
        pass
    # 平台识别
    assert A.detect_platform("NVIDIA Jetson Nano Developer Kit", root="/nonexist") == "jetson"
    assert A.detect_platform("Raspberry Pi 4 Model B Rev 1.4", root="/nonexist") == "rpi"
    assert A.detect_platform("D-Robotics RDK X5", root="/nonexist") == "rdk"
    assert A.detect_platform("Sipeed MaixCAM", root="/nonexist") == "maixcam"
    assert A.detect_platform("", root="/nonexist") == "pc"
    # 假根目录 + 假串口：ttyTHS1 静默，ttyUSB0 有 MCU 心跳 → 选 ttyUSB0
    with tempfile.TemporaryDirectory() as r:
        os.makedirs(os.path.join(r, "dev"))
        for n in ("ttyTHS1", "ttyUSB0"):
            open(os.path.join(r, "dev", n), "w").close()
        hb = encode(HEARTBEAT, 0, 7, b"\x01\x02")

        class Fake:
            def __init__(self, dev, baud):
                self.data = hb if dev.endswith("ttyUSB0") else b""

            def read(self, n):
                d, self.data = self.data, b""
                return d

            def close(self):
                pass
        os.environ.pop("DZ_SERIAL", None)
        assert A.candidates("jetson", root=r) == ["/dev/ttyTHS1", "/dev/ttyUSB0"]
        dev, why = A.find_serial(platform="jetson", opener=Fake, root=r, probe_s=0.05)
        assert dev == "/dev/ttyUSB0" and "已确认" in why, (dev, why)
        os.remove(os.path.join(r, "dev", "ttyUSB0"))
        dev, why = A.find_serial(platform="jetson", opener=Fake, root=r, probe_s=0.05)
        assert dev == "/dev/ttyTHS1" and "未确认" in why
        os.environ["DZ_SERIAL"] = "/dev/ttyX"
        assert A.find_serial(platform="jetson", opener=Fake, root=r)[0] == "/dev/ttyX"
        os.environ.pop("DZ_SERIAL")
    print("sender/autodetect 自测通过")


if __name__ == "__main__":
    main()
