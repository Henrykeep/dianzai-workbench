"""工作台 ↔ Linux 协处理器的集成接口（第 0 阶段：只定义接口，未实现）。

工作台将来通过 board.yaml 的 coprocessor.linux 段：
  * connect()  —— 打开 link 指定的串口/网口，实时显示通道数据（复用 Link.poll）
  * logs()     —— 按 linux.log.method 取日志（journalctl -u <service> / tail 文件 / dzframe 日志通道）
  * deploy()   —— 按 linux.deploy.method 把程序目录同步到 remote_dir 并重启 entry/service（ssh+rsync 或 adb push）
不在本阶段实现的原因：需要真实设备与登录方式，无法在仓库内验证；接口先固定下来，避免日后各板各写一套。
"""


class CoprocessorSession:
    def __init__(self, board: dict):
        if board.get("kind") != "coprocessor" or board["coprocessor"].get("class") != "linux_vision":
            raise ValueError("只支持 kind=coprocessor 且 class=linux_vision 的板卡")
        self.board = board
        self.linux = board["coprocessor"].get("linux") or {}

    def connect(self):
        raise NotImplementedError("第 0 阶段预留：见 docs/08-协处理板与软核.md")

    def logs(self, follow: bool = True):
        raise NotImplementedError("第 0 阶段预留：见 docs/08-协处理板与软核.md")

    def deploy(self, local_dir: str):
        raise NotImplementedError("第 0 阶段预留：见 docs/08-协处理板与软核.md")
