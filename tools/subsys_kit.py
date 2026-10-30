#!/usr/bin/env python3
"""子系统搬家工具：声明（subsys.yaml）→ 加进别的题目 / 从题目里拿掉，不改子系统代码。

  python3 tools/subsys_kit.py manifest <题目>/subsys/<名>          # 从代码 + project.yaml 推出 subsys.yaml（读写哪些段、哪些字段、哪些参数）
  python3 tools/add_subsys.py <源题目>/subsys/<名> <目标题目>        # 复制子系统、补齐 project.yaml、缺 io 层时生成 io/io_auto.c
  python3 tools/remove_subsys.py <题目> <名>                       # 拿掉：目录挪到 subsys/.removed/，它写的段交还 io（其他代码照常编译）

不改你的 project.yaml 格式和注释：只按行插入/改动，改前备份为 project.yaml.bak。
"""
import argparse
import datetime
import pathlib
import re
import shutil
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACC = re.compile(r"\bst->([a-z_][a-z0-9_]*)(?:\.([a-z_][a-z0-9_]*))?")
PAR = re.compile(r"\bp->([a-z_][a-z0-9_]*)")


def load(p: pathlib.Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def flow(d: dict) -> str:
    """一行流式 yaml（与 project.yaml 的写法一致）。"""
    return yaml.safe_dump(d, allow_unicode=True, default_flow_style=True, sort_keys=False, width=10**6).strip()


def manifest(sdir: pathlib.Path) -> dict:
    """从子系统源码里 st->段.字段 / p->参数 的用法 + 所在题目的 project.yaml 推出声明。"""
    proj = sdir.parent.parent
    p = load(proj / "project.yaml")
    name = sdir.name
    ent = next((s for s in p.get("subsystems") or [] if s.get("name") == name), None)
    if ent is None:
        raise SystemExit(f"✗ {proj}/project.yaml 的 subsystems 里没有 {name}")
    code = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(sdir.glob("*.c")))
    state = p.get("state") or {}
    used: dict[str, set] = {}
    for blk, fld in ACC.findall(code):
        used.setdefault(blk, set())
        if fld:
            used[blk].add(fld)
    owns = {}
    for blk in ent.get("owns") or []:
        owns[blk] = list(state[blk].get("fields") or [])
    reads = {}
    for blk in ent.get("reads") or []:
        fl = [f for f in state[blk].get("fields") or [] if f["name"] in used.get(blk, set())]
        reads[blk] = fl
    undeclared = sorted(set(used) - set(owns) - set(reads))
    if undeclared:
        raise SystemExit(f"✗ {name} 的代码用到了 {undeclared}，但 project.yaml 里没声明 owns/reads：先补声明")
    pn = set(PAR.findall(code))
    params = [x for x in p.get("params") or [] if x["name"] in pn]
    return {"name": name, "period_ms": ent.get("period_ms"), "owns": owns, "reads": reads, "params": params}


def write_manifest(sdir: pathlib.Path, write: bool = True):
    m = manifest(sdir)
    out = sdir / "subsys.yaml"
    lines = [f"# 子系统 {m['name']} 的接口声明（tools/subsys_kit.py manifest 从代码推出；代码改了读写就重跑）。",
             "# add_subsys.py 按它把子系统装进别的题目：缺的段/字段/参数自动补，没人写的段交给 io（默认 0）。",
             f"name: {m['name']}", f"period_ms: {m['period_ms']}"]
    for key in ("owns", "reads"):
        lines.append(f"{key}:")
        for blk, fl in m[key].items():
            lines.append(f"  {blk}:")
            lines += [f"    - {flow(f)}" for f in fl] or ["    []"]
    lines.append("params:")
    lines += [f"  - {flow(x)}" for x in m["params"]] or ["  []"]
    text = "\n".join(lines) + "\n"
    if not write:
        return text
    out.write_text(text, encoding="utf-8")
    return out


# ---------------------------------------------------------------- project.yaml 按行编辑
def top_span(lines: list[str], key: str) -> tuple[int, int] | None:
    for i, l in enumerate(lines):
        if re.match(rf"^{key}:", l):
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j][0] in " #-"):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            return i, j
    return None


def last_item(lines, a, b, indent):
    k = None
    for i in range(a + 1, b):
        if re.match(rf"^{' ' * indent}- ", lines[i]):
            k = i
    return k


def new_project(dst: pathlib.Path, board: str) -> str:
    return "\n".join([
        f"# {dst.name}：由 tools/add_subsys.py 新建的题目工程（结构按装进来的子系统声明自动补）。",
        "schema_version: 1", f"name: {dst.name}", "description: TODO 一句话",
        "", "boards:", f"  main: {board}", "", "state:",
        "  coord:", "    owner: coord", "    fields:", "      - { name: test_id, type: uint8 }",
        "", "subsystems:", "", "params:", "", "profiles:", "  - { name: base, desc: 默认档 }",
        "", "tests:      # TODO(用户)：按题目改", "  - { id: 1, name: 示例, profile: base, time_limit_s: 30 }", ""])


def add(src: pathlib.Path, dst: pathlib.Path, board: str) -> list[str]:
    notes = []
    sdir = src
    mf = sdir / "subsys.yaml"
    m = load(mf) if mf.exists() else manifest(sdir)
    name = m["name"]
    dst.mkdir(parents=True, exist_ok=True)
    py = dst / "project.yaml"
    if not py.exists():
        py.write_text(new_project(dst, board), encoding="utf-8")
        notes.append(f"新建 {py}")
    else:
        shutil.copy2(py, dst / "project.yaml.bak")
    p = load(py)
    if any(s.get("name") == name for s in p.get("subsystems") or []):
        raise SystemExit(f"✗ {dst} 里已经有子系统 {name}")
    target = dst / "subsys" / name
    if target.exists():
        raise SystemExit(f"✗ {target} 已存在（不覆盖）")
    shutil.copytree(sdir, target)
    lines = py.read_text(encoding="utf-8").split("\n")
    state = p.get("state") or {}

    # 段：owns → owner=name；reads 缺的段 → owner=io；已有段缺字段 → 追加
    def ensure_block(blk, fields, owner):
        nonlocal lines
        st = top_span(lines, "state")
        a, b = st
        cur = state.get(blk)
        if cur is None:
            ins = [f"  {blk}:", f"    owner: {owner}",
                   "    fields:"] + [f"      - {flow(f)}" for f in fields]
            if owner == "io":
                ins.insert(1, f"    # add_subsys.py 为 {name} 补的段：目前没人写（默认 0），在 io 层或别的子系统里接上")
            lines[b:b] = ins
            notes.append(f"state.{blk}：新建（owner {owner}，{len(fields)} 个字段）")
            return
        if owner != "io" and cur.get("owner") not in (owner, "io"):
            raise SystemExit(f"✗ 段 {blk} 已由 {cur.get('owner')} 写，{name} 也要写：一段只能有一个写者")
        have = {f["name"]: f for f in cur.get("fields") or []}
        missing = [f for f in fields if f["name"] not in have]
        for f in fields:
            if f["name"] in have and have[f["name"]].get("type") != f.get("type"):
                raise SystemExit(f"✗ {blk}.{f['name']} 类型不一致：题目里 {have[f['name']].get('type')}，{name} 要 {f.get('type')}")
        # 定位段内最后一个字段行
        hi = next(i for i in range(a + 1, b) if re.match(rf"^  {blk}:", lines[i]))
        end = hi + 1
        while end < b and (lines[end].startswith("    ") or not lines[end].strip()):
            end += 1
        while not lines[end - 1].strip():
            end -= 1
        if owner != "io" and cur.get("owner") == "io":
            for i in range(hi, end):
                if re.match(r"^    owner:\s*io\b", lines[i]):
                    lines[i] = f"    owner: {owner}"
            notes.append(f"state.{blk}：写者 io → {owner}")
        if missing:
            lines[end:end] = [f"      - {flow(f)}" for f in missing]
            notes.append(f"state.{blk}：补字段 {[f['name'] for f in missing]}")

    for blk, fl in (m.get("owns") or {}).items():
        ensure_block(blk, fl, name)
        p = yaml.safe_load("\n".join(lines)); state = p.get("state") or {}
    for blk, fl in (m.get("reads") or {}).items():
        ensure_block(blk, fl, "coord" if blk == "coord" else "io")
        p = yaml.safe_load("\n".join(lines)); state = p.get("state") or {}

    # 参数
    have = {x["name"]: x for x in p.get("params") or []}
    miss = [x for x in m.get("params") or [] if x["name"] not in have]
    if miss:
        a, b = top_span(lines, "params")
        k = last_item(lines, a, b, 2)
        at = (k + 1) if k is not None else a + 1
        if lines[a].strip() == "params: []":
            lines[a] = "params:"
        lines[at:at] = [f"  - {flow(x)}" for x in miss]
        notes.append(f"params：补 {len(miss)} 个（带原题目的默认值/范围）")

    # 子系统条目
    a, b = top_span(lines, "subsystems")
    if lines[a].strip() == "subsystems: []":
        lines[a] = "subsystems:"
    k = last_item(lines, a, b, 2)
    at = (k + 1) if k is not None else a + 1
    ent = {"name": name, "board": "main", "period_ms": m["period_ms"],
           "owns": list((m.get("owns") or {}).keys()), "reads": list((m.get("reads") or {}).keys())}
    lines[at:at] = [f"  - {flow(ent)}"]
    py.write_text("\n".join(lines), encoding="utf-8")
    notes.append(f"subsystems：加 {name}")

    # io 层：题目里没人提供 app_init 时，按声明 + 板上资源 + 接线表生成
    has_app = any(re.search(r"\bapp_init\s*\(\s*void\s*\)\s*\{", f.read_text(encoding="utf-8", errors="replace"))
                  for f in dst.rglob("*.c") if "/tests/" not in str(f) and f.name != "io_auto.c")
    if not has_app:
        r = gen_io(dst)
        LAST_IO.clear(); LAST_IO.update(r)
        if r["written"]:
            notes.append(f"io/io_auto.c：自动接线 {r['binds']} 个字段；TODO {len(r['todo'])} 处，确认 {len(r['confirm'])} 处")
        else:
            notes.append("io/io_auto.c 你改过了，没覆盖（删掉它再跑一次会重新生成）")
        notes += [f"  TODO {t}" for t in r["todo"]] + [f"  确认 {c}" for c in r["confirm"]]
    if not (dst / "app.yaml").exists():
        (dst / "app.yaml").write_text(f"name: {dst.name}\nversion: 0.1.0\nrequires: {{}}\n", encoding="utf-8")
    return notes


LAST_IO: dict = {}
BINDINGS = ROOT / "tools" / "catalog" / "io_bindings.yaml"
AUTO_MARK = "/* dz-io-auto "


def board_res(name: str | None) -> dict[str, set]:
    import os
    f = pathlib.Path(os.environ.get("DZ_BOARDS_DIR") or ROOT / "boards") / str(name) / "board.yaml"
    if not name or not f.exists():
        return {}
    res = (load(f).get("resources") or {})
    return {t: {r["name"] for r in (v or []) if isinstance(r, dict) and "name" in r} for t, v in res.items()}


def plan_io(p: dict, res: dict[str, set], rules: list[dict]):
    """每个需要 io 接的字段 → 唯一驱动绑定 / TODO（没规则、板上缺资源、有歧义）。"""
    state = p.get("state") or {}
    binds, groups = [], {}
    for blk, d in state.items():
        owner = (d or {}).get("owner")
        if owner == "coord":
            continue
        direction = "read" if owner == "io" else "write"
        for f in (d or {}).get("fields") or []:
            fn = f["name"]
            hits, missing = [], []
            for r in rules:
                if r["dir"] != direction:
                    continue
                m = re.match(r["field"], fn)
                if not m:
                    continue
                x = (m.groupdict().get("x") or "").upper()
                need = {t: [n.replace("{X}", x) for n in ns] for t, ns in (r.get("res") or {}).items()}
                lack = [f"{t}.{n}" for t, ns in need.items() for n in ns if n not in res.get(t, set())]
                (missing if lack else hits).append((r, need, x, lack))
            if len(hits) == 1:
                r, need, x, _ = hits[0]
                binds.append({"block": blk, "field": fn, "driver": r["driver"], "res": need, "x": x})
            elif len(hits) > 1:
                why = "有歧义，板上同时有 " + " / ".join(
                    f"{h[0]['driver']}({', '.join(n for ns in h[1].values() for n in ns)})" for h in hits) \
                    + "：在 tools/catalog/io_bindings.yaml 或板子资源里留一个"
                groups.setdefault((blk, why), []).append(fn)
            elif missing:
                why = "板上缺 " + "；".join(f"{h[0]['driver']} 要的 {', '.join(h[3])}" for h in missing)
                groups.setdefault((blk, why), []).append(fn)
            elif direction == "read":
                groups.setdefault((blk, "没有接线规则：在 io_read() 里自己填，或给 io_bindings.yaml 加一条"), []).append(fn)
    todo = [f"{blk}.{{{', '.join(fs)}}}：{why}" if len(fs) > 1 else f"{blk}.{fs[0]}：{why}" for (blk, why), fs in groups.items()]
    return binds, todo


def _c_io(p: dict, binds: list[dict], todo: list[str], board: str) -> tuple[str, list[str]]:
    pn = {x["name"]: x for x in p.get("params") or []}
    confirm = []
    inc, decl, init, rd, wr = set(), [], [], [], []
    by = {}
    for b in binds:
        by.setdefault((b["driver"], b["x"]), []).append(b)
    for (drv, x), bs in by.items():
        r = bs[0]["res"]
        g = " && ".join(f"defined(RES_{t.upper()}_{n})" for t, ns in r.items() for n in ns)
        def P(t, i=0):
            return f"RES_{t.upper()}_{r[t][i]}"
        lo = x.lower()
        if drv == "motor_dc":
            inc.add("motor_dc.h")
            decl.append(f"#if {g}\nstatic motor_dc_t M_{x};\n#endif")
            init.append(f"#if {g}\n    {{ motor_dc_cfg_t c = motor_dc_cfg_default(); c.pwm = {P('pwm')}; c.in1 = {P('gpio')}; c.in2 = {P('gpio', 1)}; c.max_duty = 0.9f;\n"
                        f"      if ((e = motor_dc_init(&M_{x}, &c)) != DZ_OK) return e; }}\n#endif")
            for b in bs:
                wr.append(f"#if {g}\n    if (cs == COORD_RUNNING) motor_dc_set(&M_{x}, st->{b['block']}.{b['field']});\n"
                          f"    else motor_dc_stop(&M_{x}, cs == COORD_ESTOP ? MOTOR_DC_BRAKE : MOTOR_DC_COAST);\n#endif")
        elif drv == "encoder":
            inc.add("encoder.h")
            cpr = pn.get("counts_per_rev", {}).get("default")
            circ = pn.get("wheel_circ_m", {}).get("default")
            if cpr is None:
                confirm.append("IO_COUNTS_PER_REV（编码器每圈计数，默认 1000：按实物标定）")
            if circ is None and any(b["field"].endswith("_mps") for b in bs):
                confirm.append("IO_WHEEL_CIRC_M（轮周长，默认 0.2 m：量一下）")
            decl.append(f"#if {g}\nstatic encoder_t E_{x};\n#endif")
            init.append(f"#if {g}\n    {{ encoder_cfg_t c = encoder_cfg_default(); c.enc = {P('encoder')}; c.counts_per_rev = IO_COUNTS_PER_REV; c.dt_s = 1e-3f; c.speed_lpf_hz = 30.0f;\n"
                        f"      if ((e = encoder_init(&E_{x}, &c)) != DZ_OK) return e; }}\n#endif")
            rd.append(f"#if {g}\n    (void)encoder_update(&E_{x});\n" + "".join(
                f"    st->{b['block']}.{b['field']} = encoder_speed_rps(&E_{x})" + (" * IO_WHEEL_CIRC_M" if b["field"].endswith("_mps") else "") + ";\n"
                for b in bs) + "#endif")
        elif drv == "qd4310_angle":
            inc.add("qd4310.h")
            decl.append(f"#if {g}\nstatic qd4310_t BEAM_DRV;\n#endif")
            init.append(f"#if {g}\n    if ((e = qd4310_init(&BEAM_DRV, {P('uart')}, 0u)) != DZ_OK) return e;\n    (void)qd4310_enable(&BEAM_DRV, true);\n#endif")
            confirm.append("QD4310 电机 ID（生成时用 0）")
            for b in bs:
                wr.append(f"#if {g}\n    (void)qd4310_poll(&BEAM_DRV);\n    if (cs == COORD_RUNNING && now_ms % 10u == 0u) (void)qd4310_set_angle_deg(&BEAM_DRV, st->{b['block']}.{b['field']});\n#endif")
        elif drv == "servo_angle":
            inc.add("servo.h")
            decl.append(f"#if {g}\nstatic servo_t SERVO_DRV;\n#endif")
            init.append(f"#if {g}\n    {{ servo_cfg_t c = servo_cfg_default({P('pwm')}); if ((e = servo_init(&SERVO_DRV, &c)) != DZ_OK) return e; }}\n#endif")
            for b in bs:
                wr.append(f"#if {g}\n    if (cs == COORD_RUNNING) (void)servo_set_deg(&SERVO_DRV, st->{b['block']}.{b['field']});\n#endif")
        elif drv in ("imu_wit", "imu_mpu6050"):
            fl = {b["field"]: b["block"] for b in bs}
            if drv == "imu_wit":
                inc.add("wit_imu.h")
                decl.append(f"#if {g}\nstatic wit_t IMU_DRV;\n#endif")
                init.append(f"#if {g}\n    {{ wit_cfg_t c = {{ {P('uart')}, WIT_JY61P, 100u, 100u }}; if ((e = wit_init(&IMU_DRV, &c)) != DZ_OK) return e; }}\n#endif")
                confirm.append("维特 IMU 型号（生成时按 JY61P）和安装方向（取 x 轴为前向）")
                body = "    (void)wit_poll(&IMU_DRV, now_ms);\n"
                vals = {"imu_ax_mps2": "wit_data(&IMU_DRV)->acc_g[0] * 9.80665f", "imu_ok": "wit_fresh(&IMU_DRV, now_ms)",
                        "imu_rx_ms": "wit_data(&IMU_DRV)->t_angle_ms"}
            else:
                inc.add("mpu6050.h")
                decl.append(f"#if {g}\nstatic mpu6050_t IMU_DRV;\n#endif")
                init.append(f"#if {g}\n    {{ mpu6050_cfg_t c = mpu6050_cfg_default({P('i2c')}); if ((e = mpu6050_init(&IMU_DRV, &c)) != DZ_OK) return e; }}\n#endif")
                confirm.append("MPU6050 安装方向（取 x 轴为前向）")
                body = "    static mpu6050_data_t d; static bool ok; static uint32_t t;\n    if (now_ms % 10u == 0u) { ok = mpu6050_read(&IMU_DRV, &d) == DZ_OK; if (ok) t = now_ms; }\n"
                vals = {"imu_ax_mps2": "d.acc[0]", "imu_ok": "ok", "imu_rx_ms": "t"}
            rd.append(f"#if {g}\n    {{\n{body}" + "".join(f"    st->{blk}.{f} = {vals[f]};\n" for f, blk in fl.items()) + "    }\n#endif")
    cpr = pn.get("counts_per_rev", {}).get("default", 1000)
    circ = pn.get("wheel_circ_m", {}).get("default", 0.2)
    head = (f"/* 自动生成（tools/subsys_kit.py，板 {board}），按 project.yaml 的读写声明 + tools/catalog/io_bindings.yaml 接线。\n"
            " * 没改过就会被重新生成；改了就不再覆盖（生成器会提示）。io_read/io_write 是弱函数：想整个自己写就在别的 .c 里实现同名函数。\n"
            + "".join(f" * TODO {t}\n" for t in todo) + "".join(f" * 确认 {c}\n" for c in confirm) + " */\n")
    c = head + '#include "project_gen.h"\n#include "app.h"\n#include "pal.h"\n#include "board_gen.h"\n' + "".join(f'#include "{i}"\n' for i in sorted(inc))
    c += f"\n#define IO_COUNTS_PER_REV {float(cpr)!r}f\n#define IO_WHEEL_CIRC_M   {float(circ)!r}f\n\n"
    c += "\n".join(decl) + "\n\n__attribute__((weak)) const coord_hooks_t g_project_hooks = { 0, 0, 0 };\n\n"
    c += "static dz_err_t io_auto_init(void)\n{\n    dz_err_t e = DZ_OK;\n" + "\n".join(init) + "\n    return e;\n}\n\n"
    c += "__attribute__((weak)) void io_read(shared_state_t *st, uint32_t now_ms)\n{\n    (void)st; (void)now_ms;\n" + "\n".join(rd) + "\n}\n\n"
    c += "__attribute__((weak)) void io_write(const shared_state_t *st, coord_state_t cs, uint32_t now_ms)\n{\n    (void)st; (void)cs; (void)now_ms;\n" + "\n".join(wr) + "\n}\n"
    c += """
static shared_state_t S;
static subsys_sched_t SCHED;
static coord_t COORD;

dz_err_t app_init(void)
{
    dz_err_t e;
    if ((e = io_auto_init()) != DZ_OK) return e;
    if ((e = subsys_sched_init(&SCHED, g_project_subsys, PROJECT_N_SUBSYS, &S, &g_project_params[0])) != DZ_OK) return e;
    return coord_init(&COORD, &SCHED, g_project_tests, PROJECT_N_TESTS, g_project_profiles, PROJECT_N_PROFILES, &g_project_hooks);
}

void app_loop(void)
{
    static uint32_t last = UINT32_MAX;
    uint32_t now = pal_millis();
    if (now == last) return;
    last = now;
    io_read(&S, now);
    coord_poll(&COORD, now);
    io_write(&S, coord_state(&COORD), now);
}
"""
    return c, confirm


def gen_io(dst: pathlib.Path, board: str | None = None) -> dict:
    """生成/刷新 io/io_auto.c。返回 {todo:[…], confirm:[…], written:bool}。"""
    import hashlib
    p = load(dst / "project.yaml")
    board = board or (p.get("boards") or {}).get("main")
    rules = yaml.safe_load(BINDINGS.read_text(encoding="utf-8")) or []
    binds, todo = plan_io(p, board_res(board), rules)
    code, confirm = _c_io(p, binds, todo, str(board))
    confirm = list(dict.fromkeys(confirm))
    out = dst / "io" / "io_auto.c"
    out.parent.mkdir(exist_ok=True)
    if out.exists():
        old = out.read_text(encoding="utf-8")
        m = re.search(r"/\* dz-io-auto ([0-9a-f]{16}) \*/\n", old)
        body = old[m.end():] if m else None
        if not m or hashlib.sha256(body.encode()).hexdigest()[:16] != m.group(1):
            return {"todo": todo, "confirm": confirm, "written": False, "binds": len(binds)}
    h = hashlib.sha256(code.encode()).hexdigest()[:16]
    out.write_text(f"{AUTO_MARK}{h} */\n" + code, encoding="utf-8")
    return {"todo": todo, "confirm": confirm, "written": True, "binds": len(binds)}


def remove(proj: pathlib.Path, name: str) -> list[str]:
    py = proj / "project.yaml"
    p = load(py)
    if not any(s.get("name") == name for s in p.get("subsystems") or []):
        raise SystemExit(f"✗ {py} 里没有子系统 {name}")
    shutil.copy2(py, proj / "project.yaml.bak")
    lines = py.read_text(encoding="utf-8").split("\n")
    notes = []
    a, b = top_span(lines, "subsystems")
    for i in range(a + 1, b):
        if re.match(rf"^\s*-\s*\{{\s*name:\s*{name}\s*,", lines[i]):
            lines[i] = f"  # - 已用 remove_subsys.py 拿掉（{datetime.date.today()}）：{lines[i].strip()[2:]}"
            break
    else:
        raise SystemExit("✗ 子系统条目不是一行流式写法，请手动删这一条（工具不猜多行格式）")
    owned = [k for k, v in (p.get("state") or {}).items() if (v or {}).get("owner") == name]
    sa, sb = top_span(lines, "state")
    cur = None
    for i in range(sa + 1, sb):
        mm = re.match(r"^  ([a-z_][a-z0-9_]*):", lines[i])
        if mm:
            cur = mm.group(1)
        elif cur in owned and re.match(rf"^    owner:\s*{name}\b", lines[i]):
            lines[i] = f"    owner: io   # 原写者 {name} 已拿掉（remove_subsys.py）；段保留，别处代码照常编译"
    py.write_text("\n".join(lines), encoding="utf-8")
    for blk in owned:
        readers = [s["name"] for s in p.get("subsystems") or [] if blk in (s.get("reads") or []) and s["name"] != name]
        notes.append(f"state.{blk} 交还 io" + (f"；{readers} 还在读它，现在没人更新（保持 0/最后值）" if readers else ""))
    src = proj / "subsys" / name
    if src.exists():
        dest = proj / "subsys" / ".removed" / f"{name}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        notes.append(f"代码挪到 {dest.relative_to(proj)}（不编译、不删；挪回来 + 恢复 project.yaml.bak 即复原）")
    return notes


def main(argv=None, mode=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if mode is None:
        ap.add_argument("cmd", choices=["manifest", "add", "remove"])
    ap.add_argument("a")
    ap.add_argument("b", nargs="?")
    ap.add_argument("--board", default="host-sim", help="新建题目时 boards.main 用哪块板")
    a = ap.parse_args(argv)
    cmd = mode or a.cmd
    if cmd == "manifest":
        print(f"✓ {write_manifest(pathlib.Path(a.a))}")
        return 0
    if not a.b:
        ap.error("缺参数")
    notes = add(pathlib.Path(a.a), pathlib.Path(a.b), a.board) if cmd == "add" else remove(pathlib.Path(a.a), a.b)
    for n in notes:
        print("  · " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
