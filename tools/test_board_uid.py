#!/usr/bin/env python3
"""换板指纹（dzctl 0.16.0 / PAL 1.9.0）：同一份 host-sim 固件，DZ_SIM_UID 模拟两块板 →
schema_hash 相同、board_uid64 不同且非 0；同一块板重启 → board_uid64 不变（可复现）；与 pal_uid64 的 FNV-1a 64 对拍。make test 调用。"""
import os, pathlib, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app/sidecar"))
from dzbench._dzlink import HEARTBEAT, Parser  # noqa: E402
from dzbench.transport import sim_elf  # noqa: E402

APP = "car_2wd"


def fnv64(b: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in b:
        h = ((h ^ c) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h or 1


def heartbeat(uid: str | None) -> tuple[int, int]:
    env = {k: v for k, v in os.environ.items() if k != "DZ_SIM_UID"}
    if uid is not None:
        env["DZ_SIM_UID"] = uid
    p = subprocess.Popen([str(sim_elf(APP)), "--stream", "1.0"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=env, bufsize=0)
    parser, t0 = Parser(), time.monotonic()
    try:
        while time.monotonic() - t0 < 10:
            b = os.read(p.stdout.fileno(), 4096)
            if not b:
                break
            for kind, _id, _seq, pl in parser.feed(b):
                if kind == HEARTBEAT and len(pl) >= 48:
                    return (int.from_bytes(pl[0:4], "little"),
                            int.from_bytes(pl[40:44], "little") | int.from_bytes(pl[44:48], "little") << 32)
    finally:
        p.kill(); p.wait()
    raise SystemExit(f"✗ [board_uid] {APP}: 10 s 内没收到 len≥48 的心跳")


subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={APP}"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
fail = 0
ha, ua = heartbeat("board-A-0001")
hb, ub = heartbeat("board-B-0002")
ha2, ua2 = heartbeat("board-A-0001")
hd, ud = heartbeat(None)
if ha != hb:
    print(f"✗ [board_uid] 同一份固件两块板 schema_hash 不同：0x{ha:08X} / 0x{hb:08X}"); fail = 1
if ua == ub or 0 in (ua, ub):
    print(f"✗ [board_uid] 两块板 board_uid 应不同且非 0：{ua:016x} / {ub:016x}"); fail = 1
if (ha2, ua2) != (ha, ua):
    print("✗ [board_uid] 同一块板重启 board_uid / schema_hash 变了"); fail = 1
if ua != fnv64(b"board-A-0001") or ud != fnv64(b"dz-host-sim"):
    print(f"✗ [board_uid] 与 FNV-1a 64 对拍不一致：{ua:016x} / {ud:016x}"); fail = 1
if not fail:
    print(f"✓ 换板指纹：schema_hash 0x{ha:08X} 两板相同；board_uid A={ua:016x} B={ub:016x} 不同；默认 {ud:016x} 可复现")
sys.exit(fail)
