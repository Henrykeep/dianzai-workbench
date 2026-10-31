"""docs/dev/roles.json 必须与 tools/gen_link.py 的 ROLES 一致，并被 git 跟踪（stage_win_repo.sh 据此打进安装包）。"""
import json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_link  # noqa: E402


def test_roles_json_matches_enum():
    doc = json.loads((ROOT / "docs/dev/roles.json").read_text(encoding="utf-8"))
    assert [r["code"] for r in doc["roles"]] == list(gen_link.ROLES)
    assert all(r["zh"] for r in doc["roles"])
    assert (ROOT / "docs/dev/roles.json").read_text(encoding="utf-8") == gen_link.roles_json()


def test_roles_json_tracked_for_packaging():
    out = subprocess.run(["git", "ls-files", "docs/dev/roles.json"], cwd=ROOT, capture_output=True, text=True).stdout
    assert out.strip() == "docs/dev/roles.json"


if __name__ == "__main__":
    test_roles_json_matches_enum(); test_roles_json_tracked_for_packaging(); print("✓ roles.json")
