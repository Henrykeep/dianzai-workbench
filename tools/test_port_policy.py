#!/usr/bin/env python3
"""G4 守护自测：stm32f4-hal 已冻结——存量两块板通过，任何新板用它都报错。"""
import pathlib, sys, yaml
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import boardlib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ok = True
base = yaml.safe_load((ROOT / "boards/stm32f407-skystar/board.yaml").read_text(encoding="utf-8"))
for name, want_err in (("stm32f407-skystar", False), ("dji-rm-c", False), ("my-new-f4", True)):
    b = dict(base, name=name)
    rep = boardlib.Report()
    boardlib.generic_check(b, rep)
    hit = any("已冻结" in e for e in rep.errors)
    ok &= hit == want_err
    print(f"{'✓' if hit == want_err else '✗'} {name}: {'拒绝' if hit else '放行'}")
sys.exit(0 if ok else 1)
