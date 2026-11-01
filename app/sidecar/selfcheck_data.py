"""独立自检入口：python <安装目录>/app/sidecar/selfcheck_data.py
嵌入式 Python 会忽略 PYTHONPATH，所以这里自己把本目录放进 sys.path；输出与 op selfcheck_data 相同的 JSON，缺文件退出 1。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dzbench import datafiles, stdio_utf8  # noqa: E402

stdio_utf8.ensure()                     # #146：控制台代码页是 cp1252/cp936 也输出 UTF-8

if __name__ == "__main__":
    sys.exit(datafiles.main())
