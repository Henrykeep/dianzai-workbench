"""假 pyocd.debug.rtt：接口照抄 pyOCD 主干（RTTControlBlock.from_target / start / up_channels / down_channels）。"""
import pyocd


class _Up:
    name = "Terminal"

    def read(self):
        b = bytes(pyocd.RTT_UP)
        pyocd.RTT_UP.clear()
        return b


class _Down:
    name = "Terminal"

    def write(self, data, blocking=False):
        n = min(len(data), 16)                 # 模拟缓冲区小：一次写不完
        pyocd.RTT_DOWN.extend(data[:n])
        return n


class RTTError(Exception):
    pass


class RTTControlBlock:
    @classmethod
    def from_target(cls, target, address=None, size=None, control_block_id=b"SEGGER RTT"):
        pyocd.LOG.append(("rtt_cb", address, size))
        return cls()

    def start(self):
        if not getattr(pyocd, "RTT_PRESENT", True):
            raise RTTError("Control block not found")
        self.up_channels, self.down_channels = [_Up()], [_Down()]
