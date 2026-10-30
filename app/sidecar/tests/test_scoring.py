"""评分页后端：读评分项、按 docs/verify 规范存证据（dzbench/scoring.py；目录由 tools/req.py newlog 建）。"""
import base64, json, pathlib, types, pytest
from dzbench import scoring

REPO = pathlib.Path(__file__).resolve().parents[3]


def _svc(root):
    def yt(): raise RuntimeError("no board")
    return types.SimpleNamespace(gw=types.SimpleNamespace(root=root), yaml_target=yt)


def test_items_from_repo():
    r = scoring.items(_svc(REPO), {})
    assert r["items"] and r["candidates"] and r["path"].endswith("requirements.yaml")
    assert all("metrics" in it and "id" in it for it in r["items"])


def test_save_evidence(tmp_path):
    (tmp_path / "tools").symlink_to(REPO / "tools")
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
    r = scoring.save(_svc(tmp_path), {"code": "T1", "item": "B1", "layer": "bench", "summary": {"verdict": "台架通过（未现场验收）", "result": "PASS"},
                                      "runs": [{"n": 1, "csv": "t_s,y\n0,1\n", "png_b64": "data:image/png;base64," + png, "result": {"pass": True}}]})
    d = tmp_path / r["dir"]
    assert r["dir"].startswith("docs/verify/T1/logs/") and "_taskB1_bench" in r["dir"]
    assert (d / "run_01.csv").read_text() == "t_s,y\n0,1\n" and (d / "run_01.png").read_bytes().startswith(b"\x89PNG")
    assert json.loads((d / "result.json").read_text())["summary"]["result"] == "PASS"
    assert "现场" in (d / "notes.md").read_text(encoding="utf-8")
    with pytest.raises(scoring.ScoreError):
        scoring.save(_svc(tmp_path), {"code": "../x", "item": "B1"})
