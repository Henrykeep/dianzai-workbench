#!/usr/bin/env python3
"""校验 board.yaml：Schema + 引脚/定时器/DMA 冲突 + 可选的应用资源需求。

用法：
  python3 tools/validate_board.py boards/stm32f407-skystar/board.yaml
  python3 tools/validate_board.py boards/xxx/board.yaml --app apps/motor_speed_demo/app.yaml
  python3 tools/validate_board.py boards/*/board.yaml --strict      # TODO 也算错误

退出码：0 通过；1 有错误；2 文件无法读取
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boardlib  # noqa: E402
import yaml  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boards", nargs="+", type=pathlib.Path)
    ap.add_argument("--app", type=pathlib.Path, help="应用的 app.yaml，检查资源是否齐全")
    ap.add_argument("--strict", action="store_true", help="把 TODO 视为错误")
    ap.add_argument("-q", "--quiet", action="store_true", help="只输出错误")
    a = ap.parse_args()

    worst = 0
    for path in a.boards:
        try:
            board = boardlib.load_board(path)
        except Exception as e:  # noqa: BLE001
            print(f"✗ {path}: 无法读取：{e}")
            worst = max(worst, 2)
            continue
        rep = boardlib.check_board(board)
        if a.app and not rep.errors:
            boardlib.check_requires(board, yaml.safe_load(a.app.read_text(encoding="utf-8")), rep)
        if a.strict:
            rep.errors += [f"[TODO] {t}" for t in rep.todos]
        status = "✗" if rep.errors else "✓"
        print(f"{status} {path}  错误 {len(rep.errors)} / 警告 {len(rep.warnings)} / TODO {len(rep.todos)}")
        for m in rep.errors:
            print(f"   错误  {m}")
        if not a.quiet:
            for m in rep.warnings:
                print(f"   警告  {m}")
            if not a.strict:
                for t in rep.todos:
                    print(f"   TODO  {t}")
        if rep.errors:
            worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    sys.exit(main())
