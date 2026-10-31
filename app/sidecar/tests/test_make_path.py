"""projflow.make_path：Keil/HAL 注入源路径同盘相对工程根，跨盘保留正斜杠绝对路径。"""
import ntpath
import posixpath

from dzbench import projflow


def test_same_drive_relative(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    assert projflow.make_path(str(tmp_path / "Car" / "Drivers"), root) == "../Car/Drivers"
    win = lambda p, r: ntpath.relpath(p, r)
    assert projflow.make_path("C:\\Car\\Drivers", "C:\\dz\\repo", relpath=win) == "../../Car/Drivers"
    monkeypatch.setenv("CUBE_DIR", str(tmp_path / "Car"))
    assert projflow.make_env(root)["CUBE_DIR"] == "../Car"


def test_cross_drive_absolute_forward_slashes():
    win = lambda p, r: ntpath.relpath(p, r)          # C: vs D: → ValueError
    assert projflow.make_path("D:\\Car\\Drivers", "C:\\dz\\repo", relpath=win) == "D:/Car/Drivers"
    assert projflow.make_path("third_party/x", "/r") == "third_party/x"   # 已是相对路径不动
    assert posixpath  # noqa
