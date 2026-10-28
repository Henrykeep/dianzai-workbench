"""协处理器平台识别 + 串口自动探测（dzlink 1.1.0）。

    from dzlink.autodetect import detect_platform, find_serial
    plat = detect_platform()                    # "jetson" / "rpi" / "rdk" / "maixcam" / "pc" ...
    dev = find_serial(baud=115200)              # 有 MCU 心跳的口优先；没探到就按平台默认口

探测顺序：
  1. 环境变量 DZ_SERIAL（手动指定，最高优先）；
  2. 候选口 = 平台 40-pin 默认 UART + 所有 USB 串口（/dev/ttyUSB*、/dev/ttyACM*，即 USB-TTL / ST-Link VCP / DAPLink VCP）；
  3. 逐个打开、监听 probe_s 秒，收到合法 dzframe（MCU 每 500 ms 发 HEARTBEAT）就选它；
  4. 都没收到：返回平台默认口（第一个存在的候选），并在 reason 里说明“未确认”。
平台默认口来源（【未验证】均未在实机上跑过，以各家文档为准）：
  Jetson Nano 40-pin 8/10 脚 = /dev/ttyTHS1；树莓派 = /dev/serial0（需 raspi-config 关串口登录、开硬件串口）；
  地瓜 RDK X3/X5 40-pin = /dev/ttyS3（X3）/ /dev/ttyS1（X5）；MaixCAM/MaixCAM2 = /dev/ttyS0（A16/A17 等，按 MaixPy 文档的引脚复用）。
K230（CanMV，MicroPython）不是 Linux，用 host/k230/dzsend.py。
"""
import glob
import os
import sys
import time

PLATFORM_PORTS = {
    "jetson": ["/dev/ttyTHS1", "/dev/ttyTHS0"],
    "rpi": ["/dev/serial0", "/dev/ttyAMA0", "/dev/ttyS0"],
    "rdk": ["/dev/ttyS3", "/dev/ttyS1"],
    "maixcam": ["/dev/ttyS0", "/dev/ttyS1"],
    "pc": [],
}


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace").strip("\x00\n ")
    except OSError:
        return ""


def detect_platform(model=None, root="/"):
    """按 /proc/device-tree/model、/etc/nv_tegra_release、maix 模块判断平台。model/root 参数用于测试。"""
    if model is None:
        model = _read(os.path.join(root, "proc/device-tree/model"))
    m = model.lower()
    if "jetson" in m or "nvidia" in m or os.path.exists(os.path.join(root, "etc/nv_tegra_release")):
        return "jetson"
    if "raspberry pi" in m:
        return "rpi"
    if "rdk" in m or "horizon" in m or "d-robotics" in m or "sunrise" in m:
        return "rdk"
    if "maixcam" in m or "licheerv" in m or "sg200" in m or "cv18" in m:
        return "maixcam"
    if root == "/" and model == _read("/proc/device-tree/model"):
        try:
            import maix  # noqa: F401  MaixPy 只在 MaixCAM 上有
            return "maixcam"
        except ImportError:
            pass
    return "pc"


def candidates(platform=None, root="/"):
    plat = platform or detect_platform(root=root)
    pre = [p for p in PLATFORM_PORTS.get(plat, []) if os.path.exists(os.path.join(root, p.lstrip("/")))]
    usb = sorted(glob.glob(os.path.join(root, "dev/ttyUSB*")) + glob.glob(os.path.join(root, "dev/ttyACM*")))
    usb = ["/" + os.path.relpath(u, root) if root != "/" else u for u in usb]
    if sys.platform.startswith("win"):
        try:
            from serial.tools import list_ports
            usb = [p.device for p in list_ports.comports()]
        except ImportError:
            usb = []
    return pre + [u for u in usb if u not in pre]


def probe(dev, baud=115200, probe_s=1.2, opener=None):
    """打开 dev 监听 probe_s 秒，收到合法 dzframe 返回 True。opener(dev, baud) -> 有 read() 的对象（测试注入）。"""
    from .protocol import Parser
    try:
        if opener:
            s = opener(dev, baud)
        else:
            import serial
            s = serial.Serial(dev, baud, timeout=0.05)
    except Exception:
        return False
    p = Parser()
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < probe_s:
            data = s.read(256)
            if data and p.feed(data):
                return True
            if not data and opener:
                time.sleep(0.01)
    finally:
        try:
            s.close()
        except Exception:
            pass
    return False


def find_serial(baud=115200, probe_s=1.2, platform=None, opener=None, root="/"):
    """返回 (设备名或 None, 原因)。"""
    env = os.environ.get("DZ_SERIAL")
    if env:
        return env, "环境变量 DZ_SERIAL"
    cands = candidates(platform, root)
    for d in cands:
        if probe(d, baud, probe_s, opener):
            return d, "收到 MCU 的 dzframe（已确认）"
    if cands:
        return cands[0], "未收到心跳，用平台默认口（未确认：检查接线 TX↔RX、共地、波特率）"
    return None, "没有找到任何串口"


if __name__ == "__main__":
    plat = detect_platform()
    dev, why = find_serial()
    print("平台:", plat, " 候选:", candidates(plat), " 选择:", dev, "（" + why + "）")
