"""传输层：串口 / UDP / 回环（测试用）。都只需实现 write(bytes) 与非阻塞 read() -> bytes。"""
import socket


class LoopbackTransport:
    def __init__(self):
        self.buf = bytearray()

    def write(self, data: bytes):
        self.buf += data

    def read(self) -> bytes:
        d, self.buf = bytes(self.buf), bytearray()
        return d


class SerialTransport:
    def __init__(self, device: str, baud: int):
        import serial  # pyserial
        self.s = serial.Serial(device, baud, timeout=0)

    def write(self, data: bytes):
        self.s.write(data)

    def read(self) -> bytes:
        return self.s.read(self.s.in_waiting or 0)


class UdpTransport:
    """网口方案：协处理器与 MCU（带以太网/ESP32 等）或工作台之间用 UDP，一个数据报可含多帧。"""

    def __init__(self, local_port: int, remote: tuple):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", local_port))
        self.sock.setblocking(False)
        self.remote = remote

    def write(self, data: bytes):
        self.sock.sendto(data, self.remote)

    def read(self) -> bytes:
        out = bytearray()
        while True:
            try:
                out += self.sock.recv(2048)
            except BlockingIOError:
                return bytes(out)
