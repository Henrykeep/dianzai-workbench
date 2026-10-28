"""假 pyOCD（只给测试用）：接口形状与真 pyOCD 0.36 对齐，dzbench 的 PyOCDBackend 原样调用。

“芯片”就是 tests/ptyboard.PtyBoard：镜像文件内容 = 要跑的仿真应用名（如 b"car_2wd"），
reset() 时板子换成这个应用重新启动——所以烧录后的心跳 schema 哈希是真的变了/没变。
"""
BOARD = None          # 测试里设成 PtyBoard
IDCODE = 0x0BC11477   # cm0plus
FLASH = bytearray()
LOG: list = []
