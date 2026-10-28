"""MaixCAM2 端：把钢珠识别结果按 boards/maixcam2-vision/board.yaml 的 ball 通道发给主控（dzframe/1，CRC16）。

部署：把本文件和 host/python/dzlink/ 目录一起拷到相机上（相机上不需要 PyYAML，通道定义内置并由测试核对与 board.yaml 一致）。
    python3 ball_sender.py --device /dev/ttyS1      # 设备名以 MaixPy 文档为准【未验证】
识别用自写跟踪器 ball_tracker.py（颜色阈值 find_blobs + ROI + α-β 外推）；阈值 BALL_LAB 要现场标。
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


# LAB 阈值 [L_min, L_max, A_min, A_max, B_min, B_max]：钢珠高光偏亮、低饱和。占位值，必须现场用 MaixVision 阈值工具标【未验证】
BALL_LAB = [[60, 100, -15, 15, -15, 15]]


def find_ball(img, tracker):
    """返回 TrackResult（x 相对画面中心）。"""
    from ball_tracker import blobs_from_maix
    blobs = img.find_blobs(BALL_LAB, roi=tracker.roi(), pixels_threshold=tracker.min_pixels, merge=True)
    return tracker.update(blobs_from_maix(blobs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyS1")
    ap.add_argument("--baud", type=int, default=115200)
    a = ap.parse_args()
    from maix import camera, uart, app  # MaixPy，只在相机上有
    cam = camera.Camera(320, 240)
    ser = uart.UART(a.device, a.baud)
    from ball_tracker import BallTracker
    tx = BallSender(ser.write)
    trk = BallTracker(320, 240)
    t0 = time.monotonic()
    while not app.need_exit():
        img = cam.read()
        t_ms = int((time.monotonic() - t0) * 1000)          # 读到帧的时刻 ≈ 曝光结束（未计相机内部缓冲）
        r = find_ball(img, trk)
        x = r.x if (r.detected or r.predicted) else None
        tx.write(tx.frame(x, t_ms, detected=r.detected, predicted=r.predicted))


if __name__ == "__main__":
    main()
