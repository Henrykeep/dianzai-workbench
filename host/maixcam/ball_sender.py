"""MaixCAM2 端：把钢珠识别结果按 boards/maixcam2-vision/board.yaml 的 ball 通道发给主控（dzframe/1，CRC16）。

部署：把本文件和 host/python/dzlink/ 目录一起拷到相机上（相机上不需要 PyYAML，通道定义内置并由测试核对与 board.yaml 一致）。
    python3 ball_sender.py --device /dev/ttyS1      # 设备名以 MaixPy 文档为准【未验证】
识别算法 find_ball() 是占位：请换成你的实现（P1/P2 的 MaixCAM 脚本不在本仓库）。
【已实测】PC 上：编码 → dzlink.Link 解码、C 端生成的 cp_vision_cpu_ball_decode 解码（examples/2026H_ball/tests）。
【未验证】在 MaixCAM2 上运行（maix.camera / maix.uart 接口按 MaixPy 文档编写，未在实机跑过）。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from dzlink import protocol as P  # noqa: E402

# 与 boards/maixcam2-vision/board.yaml 的 channels[ball] 一致（test_ball_sender.py 会核对）
BALL_CH = {"id": 1, "name": "ball", "fields": [
    {"name": "flags", "type": "u8"}, {"name": "x_px", "type": "i16"}, {"name": "cam_ms", "type": "u32"}]}
F_VALID, F_PREDICTED, F_CALIB_STALE, F_DETECTED = 0x01, 0x02, 0x04, 0x08


class BallSender:
    def __init__(self, write):
        self.write = write
        self.seq = 0

    def frame(self, x_px, cam_ms, detected=True, predicted=False, calib_stale=False) -> bytes:
        flags = (F_VALID if detected or predicted else 0) | (F_PREDICTED if predicted else 0) \
            | (F_CALIB_STALE if calib_stale else 0) | (F_DETECTED if detected else 0)
        x = 0 if x_px is None else max(-32768, min(32767, int(round(x_px))))
        raw = P.encode(P.DATA, BALL_CH["id"], self.seq,
                       P.pack_fields(BALL_CH["fields"], {"flags": flags, "x_px": x, "cam_ms": int(cam_ms) & 0xFFFFFFFF}))
        self.seq = (self.seq + 1) & 0xFF
        return raw

    def send(self, x_px, cam_ms, **kw):
        self.write(self.frame(x_px, cam_ms, detected=x_px is not None, **kw))


def find_ball(img):
    """占位：返回钢珠中心相对画面中心的 x 像素，没找到返回 None。换成你的算法。"""
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyS1")
    ap.add_argument("--baud", type=int, default=115200)
    a = ap.parse_args()
    from maix import camera, uart, app  # MaixPy，只在相机上有
    cam = camera.Camera(320, 240)
    ser = uart.UART(a.device, a.baud)
    tx = BallSender(ser.write)
    t0 = time.monotonic()
    while not app.need_exit():
        img = cam.read()
        t_ms = int((time.monotonic() - t0) * 1000)
        tx.send(find_ball(img), t_ms)


if __name__ == "__main__":
    main()
