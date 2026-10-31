"""#38 dzctl 0.13.0 阶跃实验 / param_reject 的帧编解码：直接用仓库 tools/dzstep.py（与固件 dzstep.c 同口径），不另写一份。"""
from __future__ import annotations

import sys

from .transport import ROOT

_t = str(ROOT / "tools")
if _t not in sys.path:
    sys.path.insert(0, _t)
import dzstep  # noqa: E402,F401

STEP_ID, REJECT_ID = dzstep.STEP_ID, dzstep.REJECT_ID
HB_ITER_BUSY = dzstep.HB_ITER_BUSY
HB_SENSOR_SAT = dzstep.HB_SENSOR_SAT
