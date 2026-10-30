#!/usr/bin/env python3
"""接口指纹与版本规则检查（tools/iface_hash.py）。

把每个模块（含 VERSION 文件的目录）公开头文件里的“声明”抽出来（去注释、压空白、
按 ; 和 #define 切分），记录到仓库根目录 iface.lock.json：

  { "firmware/algo/pid": { "version": "1.0.0", "hash": "...", "decls": [...] } }

  --check   对比当前头文件与锁文件：
              * 删除或修改了已有声明（破坏兼容） -> 必须升 MAJOR
              * 只新增声明                        -> 至少升 MINOR
              * 声明没变                           -> 版本随意（PATCH 修 bug）
            版本升了但锁文件没更新，也报错，提示运行 --update。
  --update  在满足上面规则的前提下刷新锁文件（不满足时拒绝刷新）。
  --selftest 在临时目录复制 pid 模块，故意改函数签名而不升版本，证明会被拦住。
"""
import argparse, hashlib, json, os, re, shutil, sys, tempfile

SKIP_DIRS = {"build", "third_party", ".git", "fixtures", "tests", "__pycache__"}


def norm_decls(text):
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    decls = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            if re.match(r'#\s*define\s+\w+_VERSION\b', s) or re.match(r'#\s*(ifndef|define\s+\w+_H\s*$|endif|pragma|include)', s):
                continue
            if s.startswith("#define") or s.startswith("# define"):
                decls.append(re.sub(r'\s+', ' ', s))
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    body = re.sub(r'extern\s+"C"\s*\{|^\s*\}\s*$', ' ', body, flags=re.M)
    for st in body.split(";"):
        st = re.sub(r'\s+', ' ', st).strip()
        if st:
            decls.append(st + ";")
    return decls


def scan(root):
    mods = {}
    for d, dirs, fs in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        if "VERSION" not in fs:
            continue
        hs = sorted(f for f in fs if f.endswith(".h"))
        if not hs:
            continue
        decls = []
        for h in hs:
            decls += [f"{h}: {x}" for x in norm_decls(open(os.path.join(d, h), encoding="utf-8").read())]
        rel = os.path.relpath(d, root).replace(os.sep, "/")
        mods[rel] = {
            "version": open(os.path.join(d, "VERSION")).read().strip(),
            "hash": hashlib.sha256("\n".join(decls).encode()).hexdigest()[:16],
            "decls": decls,
        }
    return mods


def vt(v):
    return tuple(int(x) for x in v.split("."))


def compare(lock, cur):
    errs, notes = [], []
    for m, c in cur.items():
        old = lock.get(m)
        if old is None:
            notes.append(f"{m}: 新模块 {c['version']}（--update 后入锁）")
            continue
        ov, nv = vt(old["version"]), vt(c["version"])
        if nv < ov:
            errs.append(f"{m}: 版本倒退 {old['version']} -> {c['version']}")
            continue
        removed = sorted(set(old["decls"]) - set(c["decls"]))
        added = sorted(set(c["decls"]) - set(old["decls"]))
        if removed and nv[0] <= ov[0]:
            errs.append(f"{m}: 删除/修改了已有接口但 MAJOR 未升（{old['version']} -> {c['version']}）：")
            errs += [f"    - {x}" for x in removed[:8]] + [f"    + {x}" for x in added[:8]]
        elif added and not removed and nv[:2] <= ov[:2]:
            errs.append(f"{m}: 新增接口但 MINOR 未升（{old['version']} -> {c['version']}）：")
            errs += [f"    + {x}" for x in added[:8]]
        elif nv != ov or c["hash"] != old["hash"]:
            notes.append(f"{m}: {old['version']} -> {c['version']}，接口{'有' if c['hash'] != old['hash'] else '无'}变化，需 --update 刷新锁文件")
    for m in lock:
        if m not in cur:
            notes.append(f"{m}: 模块已删除（--update 后出锁）")
    return errs, notes


def run(root, mode):
    lockp = os.path.join(root, "iface.lock.json")
    lock = json.load(open(lockp)) if os.path.exists(lockp) else {}
    # "_pending_rewrite"：待净室重写的模块（锁段已删，等重写者升 MAJOR 后重新入锁）；在此列表里的模块不比对、不入锁
    pending = list(lock.pop("_pending_rewrite", []))
    cur = {m: c for m, c in scan(root).items() if m not in pending}
    for m in pending:
        lock.pop(m, None)
    errs, notes = compare(lock, cur)
    for e in errs:
        print("✗ " + e)
    if mode == "update":
        if errs:
            print("iface_hash: 存在违反版本规则的改动，拒绝更新锁文件")
            return 1
        out = dict(cur)
        if pending:
            out["_pending_rewrite"] = pending
        with open(lockp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        print(f"iface_hash: 已写入 {len(cur)} 个模块到 iface.lock.json")
        return 0
    for n in notes:
        print("! " + n)
    if errs or notes:
        print(f"iface_hash: 失败（{len([e for e in errs if not e.startswith('    ')])} 处违规，{len(notes)} 处锁文件未同步）")
        return 1
    print(f"iface_hash: 通过（{len(cur)} 个模块）")
    return 0


def selftest(root):
    tmp = tempfile.mkdtemp(prefix="iface_selftest_")
    ok = True
    try:
        src = os.path.join(root, "firmware", "algo", "pid")
        dst = os.path.join(tmp, "firmware", "algo", "pid")
        shutil.copytree(src, dst)
        assert run(tmp, "update") == 0
        h = os.path.join(dst, "pid.h")
        orig = open(h, encoding="utf-8").read()
        cur = open(os.path.join(dst, "VERSION")).read().strip()          # 用模块当前版本，不写死
        M, m, _ = (int(x) for x in cur.split("."))
        minor = f"{M}.{m + 1}.0"

        def case(name, text, version, expect_fail):
            nonlocal ok
            open(h, "w", encoding="utf-8").write(text)
            open(os.path.join(dst, "VERSION"), "w").write(version + "\n")
            print(f"--- {name}")
            rc = run(tmp, "check")
            good = (rc != 0) == expect_fail
            ok &= good
            print(f"{'✓' if good else '✗'} {name}: {'被拦截' if rc else '放行'}（期望{'拦截' if expect_fail else '放行'}）")

        changed = re.sub(r'float\s+pid_update\s*\(', 'double pid_update(', orig, count=1)
        assert changed != orig, "pid.h 中找不到 pid_update 声明"
        case("改函数签名、不升版本", changed, cur, True)
        case("改函数签名、只升 MINOR", changed, minor, True)
        added = orig.replace("#endif", "int pid_new_api(void);\n#endif", 1) if "#endif" in orig else orig + "\nint pid_new_api(void);\n"
        case("只新增函数、不升版本", added, cur, True)
        case("改注释、不升版本", orig.replace("/*", "/* 注释改动 ", 1), cur, False)
    finally:
        shutil.rmtree(tmp)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--update", action="store_true")
    g.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.selftest:
        sys.exit(0 if selftest(root) else 1)
    sys.exit(run(root, "update" if a.update else "check"))


if __name__ == "__main__":
    main()
