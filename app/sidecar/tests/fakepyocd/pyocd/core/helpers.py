import pyocd


class _Mem:
    length = 64 * 1024


class _MemMap:
    def get_boot_memory(self):
        return _Mem()


class _Idr:
    @property
    def idr(self):
        return pyocd.IDCODE


class _Dp:
    dpidr = _Idr()


class _Target:
    dp = _Dp()
    memory_map = _MemMap()

    def read_memory_block8(self, addr, n):
        pyocd.LOG.append(("read", addr, n))
        return list(bytes(pyocd.FLASH[:n]).ljust(n, b"\xff"))

    def resume(self):
        pyocd.LOG.append(("resume",))

    def reset(self):
        pyocd.LOG.append(("reset",))
        app = bytes(pyocd.FLASH).rstrip(b"\xff\x00").decode()
        pyocd.BOARD.restart(app)


class Session:
    target = _Target()

    def open(self):
        pyocd.LOG.append(("open",))

    def close(self):
        pyocd.LOG.append(("close",))


class ConnectHelper:
    @staticmethod
    def session_with_chosen_probe(unique_id=None, target_override=None, blocking=True, **options):
        pyocd.LOG.append(("connect", target_override))
        if options.get("pack"):
            pyocd.LOG.append(("pack", options["pack"]))
        return Session() if pyocd.BOARD is not None else None

    @staticmethod
    def get_all_connected_probes(blocking=True, **_):
        """假探针列表：pyocd.PROBES 可由测试改（默认一个）。"""
        class P:
            def __init__(self, uid, desc):
                self.unique_id, self.description = uid, desc
        return [P(u, d) for u, d in getattr(pyocd, "PROBES", [("FAKE0001", "Fake CMSIS-DAP")])]
