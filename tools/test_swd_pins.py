"""#56：F1/F4 板卡把 PA13/PA14（SWD）当普通脚用必须报错，gen_board 非零退出。python3 tools/test_swd_pins.py"""
import copy, pathlib, subprocess, sys, tempfile
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from boardlib import Report, load_board, FAMILY_CHECKS

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOARDS = {"stm32f1": ROOT / "boards/stm32f103c8t6-car-cubemx/board.yaml",
          "stm32f4": ROOT / "boards/stm32f407-skystar/board.yaml"}


def main():
    for fam, path in BOARDS.items():
        b = load_board(path)
        r = Report(); FAMILY_CHECKS[fam](copy.deepcopy(b), r)
        assert not any("[SWD 调试脚]" in e for e in r.errors), (fam, r.errors)
        for pin, fn in (("PA13", "SWDIO"), ("PA14", "SWCLK")):
            bb = copy.deepcopy(b)
            bb.setdefault("resources", {}).setdefault("gpio", []).append({"name": "SWDTEST", "pin": pin, "dir": "out"})
            r = Report(); FAMILY_CHECKS[fam](bb, r)
            hit = [e for e in r.errors if "[SWD 调试脚]" in e and pin in e and fn in e and "无法下载" in e and "改用" in e]
            assert hit, (fam, pin, r.errors, r.warnings)
        # 端到端：gen_board 非零退出、报错里有中文提示
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw.setdefault("resources", {}).setdefault("gpio", []).append({"name": "SWDTEST", "pin": "PA13", "dir": "out"})
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "board.yaml"; p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
            cp = subprocess.run([sys.executable, str(ROOT / "tools/gen_board.py"), str(p), "-o", str(pathlib.Path(d) / "gen")],
                                capture_output=True, text=True, cwd=ROOT)
            assert cp.returncode != 0 and "SWD 调试脚" in cp.stdout + cp.stderr, (fam, cp.returncode, cp.stdout, cp.stderr)
    print("SWD 调试脚（PA13/PA14）报错自测通过")


if __name__ == "__main__":
    main()
