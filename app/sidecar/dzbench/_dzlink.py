"""复用仓库里的 dzframe Python 实现（host/python/dzlink），不另写一份协议。"""
import pathlib
import sys

_P = pathlib.Path(__file__).resolve().parents[3] / "host" / "python"
if _P.is_dir() and str(_P) not in sys.path:
    sys.path.insert(0, str(_P))

from dzlink.protocol import DATA, HEARTBEAT, PARAM_ACK, PARAM_SET, Parser, encode  # noqa: E402,F401
