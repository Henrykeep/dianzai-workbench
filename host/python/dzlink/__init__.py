"""dzlink：Linux/视觉协处理器与 MCU 之间的统一通信库（dzframe/1）。

    from dzlink import Link
    link = Link.from_board("boards/jetson-nano-vision/board.yaml", transport=SerialTransport("/dev/ttyTHS1", 115200))
    link.send("ball", x_px=320, y_px=240, found=1)
    for ch, values in link.poll(): ...

只依赖标准库；串口需要 pyserial（pip install pyserial）。
"""
from .protocol import DATA, PARAM_SET, PARAM_ACK, HEARTBEAT, MAX_PAYLOAD, Parser, crc16, encode, pack_fields, unpack_fields
from .channels import Link
from .transport import SerialTransport, UdpTransport, LoopbackTransport
from .sender import Sender, MaixUartTransport
from .autodetect import detect_platform, find_serial

__all__ = ["DATA", "PARAM_SET", "PARAM_ACK", "HEARTBEAT", "MAX_PAYLOAD", "Parser", "crc16", "encode",
           "pack_fields", "unpack_fields", "Link", "SerialTransport", "UdpTransport", "LoopbackTransport",
           "Sender", "MaixUartTransport", "detect_platform", "find_serial"]
__version__ = "1.1.0"
