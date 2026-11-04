#!/usr/bin/env python3
"""third_party/vendored/serialweb 冒烟：文件在、许可在、内联脚本能被 node 语法检查（证明原样可用）。"""
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

D = pathlib.Path(__file__).resolve().parents[1] / "third_party/vendored/serialweb"


def main() -> int:
    html = (D / "index.html").read_text(encoding="utf-8")
    assert "AFFERO" in (D / "LICENSE").read_text(encoding="utf-8"), "LICENSE 不是原样 AGPL"
    assert "navigator.serial" in html, "index.html 里找不到串口入口"
    scripts = [m.group(1) for m in re.finditer(r"<script(?![^>]*\bsrc=)(?![^>]*type=\"(?:application/json|text/plain|importmap)\")[^>]*>(.*?)</script>", html, re.S | re.I)]
    assert scripts, "没有内联脚本"
    node = shutil.which("node")
    if not node:
        print("test_vendored_serialweb: 通过（无 node，跳过语法检查）")
        return 0
    for i, js in enumerate(scripts):
        with tempfile.NamedTemporaryFile("w", suffix=".mjs" if "import " in js[:2000] else ".js", delete=False, encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        pathlib.Path(f.name).unlink()
        if r.returncode:
            print(f"✗ 第 {i} 段内联脚本语法检查失败：{r.stderr[:400]}")
            return 1
    print(f"test_vendored_serialweb: 通过（{len(scripts)} 段内联脚本，{len(html)} 字符）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
