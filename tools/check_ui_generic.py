#!/usr/bin/env python3
"""界面不写死某道题 / 某块板：app/ui/src 和 index.html 里不许出现例题专用名（例题名表只放 src/examples.ts）。
用法：check_ui_generic.py [--selftest]"""
import pathlib, re, sys
# dz-banned-words: begin
BANNED = re.compile(r"2026H|小球|球环|motor_pos|car_2wd|ball_(?:kp|ki|kd|sp|beam)\b|pos_k\b")
# dz-banned-words: end
ALLOW = {"examples.ts"}
ROOT = pathlib.Path(__file__).resolve().parent.parent / "app" / "ui"

def scan(files):
    bad = []
    for f in files:
        if f.name in ALLOW or "fixture" in f.name:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = BANNED.search(line)
            if m:
                bad.append(f"{f}:{i}: 写死了例题专用名「{m.group(0)}」→ 改成从 schema 读，或挪到 src/examples.ts")
    return bad

def main():
    if "--selftest" in sys.argv:
        import tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        # dz-banned-words: begin   自测夹具里的禁词
        (d / "a.ts").write_text('const x = "小球";\n', encoding="utf-8")
        (d / "examples.ts").write_text('const x = "2026H_ball";\n', encoding="utf-8")
        # dz-banned-words: end
        (d / "b.ts").write_text('const y = "rpm";\n', encoding="utf-8")
        r = scan(sorted(d.iterdir()))
        assert len(r) == 1 and "a.ts" in r[0], r
        print("check_ui_generic selftest ok"); return 0
    files = sorted((ROOT / "src").rglob("*.ts")) + [ROOT / "index.html"]
    bad = scan(files)
    for b in bad: print(b)
    if bad:
        print(f"check_ui_generic: {len(bad)} 处写死例题"); return 1
    print(f"check_ui_generic: {len(files)} 个文件，没有写死例题"); return 0

if __name__ == "__main__":
    sys.exit(main())
