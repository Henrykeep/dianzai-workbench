"""协处理器 → MCU 的通用发送端（dzlink 1.1.0）：按通道定义打包 DATA 帧、自管 seq、可选限速与心跳。

    from dzlink.sender import Sender
    tx = Sender.open_auto(channels={"ball": BALL_FIELDS_ID})     # 串口自动探测（见 autodetect.py）
    tx.send("ball", flags=1, x_px=320, cam_ms=1234)

通道定义两种写法：
  - 直接给 {名字: {"id": 1, "fields": [{"name": "x_px", "type": "i16"}, ...]}}（相机上没有 PyYAML 时用）；
  - Sender.from_board("boards/xxx/board.yaml", transport)（读 board.yaml 的 channels，PC/Jetson/树莓派上）。
字段类型：u8 i8 u16 i16 u32 i32 f32（小端），payload ≤ 64 字节。整数自动截断到类型范围，避免 struct.error 让识别线程崩掉。
"""
import time

from .protocol import DATA, FMT, HEARTBEAT, MAX_PAYLOAD, encode, pack_fields

_RANGE = {"u8": (0, 0xFF), "i8": (-128, 127), "u16": (0, 0xFFFF), "i16": (-32768, 32767),
          "u32": (0, 0xFFFFFFFF), "i32": (-2 ** 31, 2 ** 31 - 1)}
_SIZE = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4, "f32": 4}


class MaixUartTransport:
    """MaixCAM（MaixPy v4）的 maix.uart；接口按 MaixPy 文档【未验证】。"""

    def __init__(self, device="/dev/ttyS0", baud=115200):
        from maix import uart
        self.u = uart.UART(device, baud)

    def write(self, data):
        self.u.write(data)

    def read(self):
        return self.u.read(-1, 0) or b""


class Sender:
    def __init__(self, transport, channels, min_period_s=0.0, clock=time.monotonic):
        for name, ch in channels.items():
            if sum(_SIZE[f["type"]] for f in ch["fields"]) > MAX_PAYLOAD:
                raise ValueError("通道 %s 超过 %d 字节" % (name, MAX_PAYLOAD))
            for f in ch["fields"]:
                if f["type"] not in FMT:
                    raise ValueError("通道 %s 字段 %s 类型 %s 不支持" % (name, f["name"], f["type"]))
        self.t = transport
        self.ch = channels
        self.seq = 0
        self.min_period_s = min_period_s
        self.clock = clock
        self._last = {}
        self.sent = self.dropped = 0

    @classmethod
    def from_board(cls, board_yaml, transport, **kw):
        import yaml
        with open(board_yaml, encoding="utf-8") as f:
            b = yaml.safe_load(f)
        chans = {c["name"]: {"id": c["id"], "fields": c["fields"]} for c in (b.get("channels") or [])}
        return cls(transport, chans, **kw)

    @classmethod
    def open_auto(cls, channels, baud=115200, **kw):
        """串口自动探测后打开（MaixCAM 上用 maix.uart，其它用 pyserial）。"""
        from .autodetect import detect_platform, find_serial
        dev, why = find_serial(baud=baud)
        if not dev:
            raise RuntimeError("找不到串口：" + why)
        if detect_platform() == "maixcam":
            t = MaixUartTransport(dev, baud)
        else:
            from .transport import SerialTransport
            t = SerialTransport(dev, baud)
        s = cls(t, channels, **kw)
        s.device, s.reason = dev, why
        return s

    def frame(self, name, **values):
        ch = self.ch[name]
        v = {}
        for f in ch["fields"]:
            x = values.get(f["name"], 0)
            if f["type"] == "f32":
                v[f["name"]] = float(x)
            else:
                lo, hi = _RANGE[f["type"]]
                v[f["name"]] = max(lo, min(hi, int(round(x))))
        raw = encode(DATA, ch["id"], self.seq, pack_fields(ch["fields"], v))
        self.seq = (self.seq + 1) & 0xFF
        return raw

    def send(self, name, **values):
        """发一帧；min_period_s 限速内的调用丢弃（返回 False）。"""
        now = self.clock()
        if self.min_period_s and now - self._last.get(name, -1e9) < self.min_period_s:
            self.dropped += 1
            return False
        self._last[name] = now
        self.t.write(self.frame(name, **values))
        self.sent += 1
        return True

    def heartbeat(self, payload=b""):
        """协处理器自己的心跳（HEARTBEAT 帧，id 0）；MCU 可据此判断视觉是否掉线。"""
        self.t.write(encode(HEARTBEAT, 0, self.seq, payload))
        self.seq = (self.seq + 1) & 0xFF
