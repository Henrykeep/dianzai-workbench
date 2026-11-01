#!/usr/bin/env python3
"""换板指纹（dzctl 0.17.0 'I' 握手信息 / PAL 1.9.0）：同一份 host-sim 固件，DZ_SIM_UID 模拟两块板 →
schema_hash 相同、board_uid 不同且 uid_supported=1；DZ_SIM_UID_UNSUPPORTED=1 → uid_supported=0、board_uid=0；
心跳保持 40 字节负载（线上 49 字节），并实测心跳帧长与频率、算 9600/115200 链路占用。make test 调用。"""
import os, pathlib, struct, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app/sidecar"))
from dzbench._dzlink import DATA, HEARTBEAT, Parser, encode  # noqa: E402
from dzbench.transport import sim_elf  # noqa: E402

APP = sys.argv[1] if len(sys.argv) > 1 else "car_2wd"   # car_2wd 自带主循环；motor_pos 走 link_app.h
CMD = 0x7E
WIRE_OVERHEAD = 9          # 2 SOF + VER + KIND + ID + SEQ + LEN + 2 CRC（dzframe 无转义）


def fnv64(b: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in b:
        h = ((h ^ c) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h or 1


def run(env_add: dict, listen_s: float = 0.0):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DZ_SIM_UID")}
    env.update(env_add)
    p = subprocess.Popen([str(sim_elf(APP)), "--stream", "1.0"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=env, bufsize=0)
    parser, info, hbs, t0, asked = Parser(), None, [], time.monotonic(), 0.0
    try:
        while time.monotonic() - t0 < 15:
            now = time.monotonic()
            if info is None and now - asked > 0.5:
                p.stdin.write(encode(DATA, CMD, 1, b"I")); p.stdin.flush(); asked = now
            b = os.read(p.stdout.fileno(), 4096)
            if not b:
                break
            for kind, id_, _seq, pl in parser.feed(b):
                if kind == HEARTBEAT:
                    hbs.append((time.monotonic(), len(pl), int.from_bytes(pl[0:4], "little")))
                elif kind == DATA and id_ == CMD and pl[:1] == b"I":
                    info = pl
            if info is not None and (not listen_s or (hbs and hbs[-1][0] - hbs[0][0] >= listen_s)):
                break
    finally:
        p.kill(); p.wait()
    if info is None:
        raise SystemExit(f"✗ [board_uid] {APP}: 15 s 内没收到 'I' 握手信息回包")
    if len(info) != 27:
        raise SystemExit(f"✗ [board_uid] 'I' 回包 len={len(info)}，应为 27（dzctl 0.18.0 info_ver 2）")
    _, ver, sh, wd, sup, lo, hi, rev, pv = struct.unpack("<cBIIBIIII", info)
    return dict(ver=ver, schema_hash=sh, wd=wd, sup=sup, uid=lo | hi << 32, rev=rev, pv=pv, hbs=hbs)


subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={APP}"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
fail = 0
A = run({"DZ_SIM_UID": "board-A-0001"}, listen_s=4.0)
B = run({"DZ_SIM_UID": "board-B-0002"})
A2 = run({"DZ_SIM_UID": "board-A-0001"})
U = run({"DZ_SIM_UID": "board-A-0001", "DZ_SIM_UID_UNSUPPORTED": "1"})
if A["ver"] != 2 or A["pv"] != 0x001200:
    print(f"✗ [board_uid] info_ver={A['ver']} proto_ver={A['pv']:#x}，应为 2 / 0x1200（0.18.0）"); fail = 1
if A["schema_hash"] != B["schema_hash"] or A["wd"] != B["wd"] or A["wd"] < 300:
    print(f"✗ [board_uid] 两块板 schema_hash/wd 应相同：{A['schema_hash']:08X}/{B['schema_hash']:08X} wd {A['wd']}/{B['wd']}"); fail = 1
if not (A["sup"] == B["sup"] == 1) or A["uid"] == B["uid"]:
    print(f"✗ [board_uid] 两块板 uid_supported 应为 1、board_uid 不同：{A['uid']:016x}/{B['uid']:016x}"); fail = 1
if A2["uid"] != A["uid"] or A["uid"] != fnv64(b"board-A-0001"):
    print("✗ [board_uid] 同板重启 board_uid 变了 / 与 FNV-1a 64 对拍不一致"); fail = 1
if U["sup"] != 0 or U["uid"] != 0 or U["schema_hash"] != A["schema_hash"]:
    print(f"✗ [board_uid] UID 不支持时应 uid_supported=0、board_uid=0：sup={U['sup']} uid={U['uid']:x}"); fail = 1
hb = A["hbs"]
lens = {n for _, n, _ in hb}
if lens != {40}:
    print(f"✗ [board_uid] 心跳负载应恒为 40 字节，实测 {sorted(lens)}"); fail = 1
if any(h != A["schema_hash"] for _, _, h in hb):
    print("✗ [board_uid] 心跳 schema_hash 与握手信息不一致"); fail = 1
if len(hb) >= 3:
    span = hb[-1][0] - hb[0][0]
    rate = (len(hb) - 1) / span
    wire = 40 + WIRE_OVERHEAD
    bps = wire * 10 * rate                      # 8N1：每字节 10 bit
    occ = {b: 100 * bps / b for b in (9600, 115200)}
    if not 1.5 <= rate <= 2.5:
        print(f"✗ [board_uid] 心跳频率 {rate:.2f} Hz，应约 2 Hz（每 500 ms）"); fail = 1
    print(f"  心跳：负载 40 B + 帧开销 {WIRE_OVERHEAD} B = 线上 {wire} B；实测 {len(hb)} 帧 / {span:.2f} s = {rate:.2f} Hz；"
          f"{bps:.0f} bit/s（8N1）→ 9600 占 {occ[9600]:.2f}%，115200 占 {occ[115200]:.3f}%")
else:
    print("✗ [board_uid] 4 s 内心跳不足 3 帧"); fail = 1
if not fail:
    print(f"✓ 'I' 握手信息：schema_hash 0x{A['schema_hash']:08X} wd {A['wd']} ms 两板相同；"
          f"board_uid A={A['uid']:016x} B={B['uid']:016x}；不支持时 uid_supported=0")
sys.exit(fail)
