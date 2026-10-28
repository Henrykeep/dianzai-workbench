#!/usr/bin/env python3
"""版本号一致性：仓库只有一个版本号（安装包 = 固件里程碑 = 标签 vX.Y.Z）。
检查 app/ui/package.json、tauri.conf.json、Cargo.toml、侧车 __version__、CHANGELOG 最新发布节是否一致。"""
import json, pathlib, re, sys
R = pathlib.Path(__file__).resolve().parents[1]
v = {
    "app/ui/package.json": json.loads((R / "app/ui/package.json").read_text("utf-8"))["version"],
    "app/src-tauri/tauri.conf.json": json.loads((R / "app/src-tauri/tauri.conf.json").read_text("utf-8"))["version"],
    "app/src-tauri/Cargo.toml": re.search(r'^version = "([^"]+)"', (R / "app/src-tauri/Cargo.toml").read_text("utf-8"), re.M)[1],
    "app/sidecar/dzbench/__init__.py": re.search(r'__version__ = "([^"]+)"', (R / "app/sidecar/dzbench/__init__.py").read_text("utf-8"))[1],
    "CHANGELOG.md": re.search(r"^## \[(\d+\.\d+\.\d+)\]", (R / "CHANGELOG.md").read_text("utf-8"), re.M)[1],
}
if len(set(v.values())) != 1:
    sys.exit("✗ 版本号不一致：\n" + "\n".join(f"  {k}: {x}" for k, x in v.items()))
print(f"✓ 版本号一致 {next(iter(v.values()))}")
