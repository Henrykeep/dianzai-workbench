"""tools/check_no_truth_leak.py：非判卷代码读真值就红；仓库现状干净。"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_no_truth_leak as C  # noqa: E402


def test_rule_flags_backend_reading_truth():
    assert C.scan('import json\nx = json.load(open("plant.json"))["feasible"]\n', True)
    assert C.scan("from randplant import gen\n", True)
    assert C.scan("import feascheck\n", False)
    assert not C.scan('x = p["kp"]\n', True)


def test_repo_clean_and_selftest():
    for a in (["--selftest"], []):
        r = subprocess.run([sys.executable, str(ROOT / "tools/check_no_truth_leak.py"), *a], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


def test_grader_is_only_truth_reader():
    hits = [p.name for p in (ROOT / "tools").glob("tunegate*.py") if "plant.json" in p.read_text("utf-8") and p.name != "tunegate.py"]
    assert set(hits) <= {"tunegate_grade.py", "tunegate_plant.py"}, hits


if __name__ == "__main__":
    for f in (test_rule_flags_backend_reading_truth, test_repo_clean_and_selftest, test_grader_is_only_truth_reader):
        f()
    print("✓ 真值泄漏守卫：规则 / 仓库现状 / 唯一判卷模块")
