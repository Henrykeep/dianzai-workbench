#!/usr/bin/env python3
"""零件库测试：没装 CadQuery 时跳过（可选依赖）；装了就核对体积（手算）、包围盒、STEP/STL 能导出且能读回。"""
import math
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import parts  # noqa: E402


def main():
    if parts.cq is None:
        print("test_parts: 跳过（没装 CadQuery）")
        return
    cq = parts.cq
    # 编码器板：40×30×3 的板减 1 个 Φ8 + 2 个 Φ2.2 + 2 个 Φ3.2 通孔
    wp, p = parts.build("encoder_bracket")
    v_hand = 40 * 30 * 3 - math.pi * 3 * (4 ** 2 + 2 * 1.1 ** 2 + 2 * 1.6 ** 2)   # 3600 − 3π·(16+2.42+5.12) = 3378.15
    v = wp.val().Volume()
    assert abs(v - v_hand) < 0.5, (v, v_hand)
    for n in parts.PARAMS:
        wp, p = parts.build(n)
        assert wp.val().isValid(), n
        bb = wp.val().BoundingBox()
        if n == "motor_mount":
            d = p["motor_d"] + 2 * p["wall"]
            assert abs(bb.xlen - d) < 1e-6 and abs(bb.zlen - d) < 1e-6, (bb.xlen, bb.zlen)    # 45 × 45 竖板
        if n == "sensor_bracket":
            assert abs(bb.xlen - p["pcb_w"]) < 1e-6
    # 改参数会变（参数化真的生效）
    a = parts.build("motor_mount")[0].val().BoundingBox().xlen
    b = parts.build("motor_mount", {"motor_d": 25.0})[0].val().BoundingBox().xlen
    assert abs(a - b - 12) < 1e-6
    with tempfile.TemporaryDirectory() as d:
        for n in parts.PARAMS:
            step, stl = parts.export(n, pathlib.Path(d))
            back = cq.importers.importStep(str(step)).val()
            assert abs(back.Volume() - parts.build(n)[0].val().Volume()) < 1e-3 * back.Volume(), n
            assert stl.stat().st_size > 1000 and stl.read_bytes()[:5] in (b"solid", stl.read_bytes()[:5])
    print(f"test_parts: {len(parts.PARAMS)} 个零件通过（CadQuery {cq.__version__}）")


if __name__ == "__main__":
    main()
