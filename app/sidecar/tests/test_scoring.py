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


def test_writeback_preview_then_confirm(tmp_path):
    import shutil, subprocess, sys, yaml
    (tmp_path / "tools").symlink_to(REPO / "tools"); (tmp_path / "schema").symlink_to(REPO / "schema")
    ex = tmp_path / "examples/2026H_ball"; ex.mkdir(parents=True)
    shutil.copy(REPO / "examples/2026H_ball/requirements.yaml", ex / "requirements.yaml")
    rq = ex / "requirements.yaml"; before = rq.read_text(encoding="utf-8")
    svc = _svc(tmp_path); m0 = {"path": "examples/2026H_ball/requirements.yaml"}
    for item in ("B3", "B4"):                          # B3 已有一条两行的证据，B4 没有 evidence 键
        d = scoring.save(svc, {"code": "2026H", "item": item, "layer": "bench", "runs": [{"n": 1, "csv": "t_s\n0\n"}], "summary": {}})["dir"]
        m = m0 | {"item": item, "dir": d, "layer": "bench", "result": "pass", "note": "台架通过（未现场验收）：最慢 1.2 s"}
        pv = scoring.writeback(svc, m)
        assert "+" in pv["diff"] and "台架通过" in pv["diff"] and rq.read_text(encoding="utf-8") == before   # 预览不写
        with pytest.raises(scoring.ScoreError):
            scoring.writeback(svc, m | {"confirm": True, "sha": "stale"})
        scoring.writeback(svc, m | {"confirm": True, "sha": pv["sha"]}); before = rq.read_text(encoding="utf-8")
    doc = yaml.safe_load(before)
    it = {x["id"]: x for x in doc["items"]}
    assert len(it["B3"]["evidence"]) == 2 and it["B3"]["evidence"][0]["layer"] == "unit" and it["B4"]["evidence"][0]["result"] == "pass"
    assert "forbidden_claims" in it["B3"]
    r = subprocess.run([sys.executable, "tools/req.py", "check", str(rq)], cwd=tmp_path, capture_output=True, text=True)
    bad = [l for l in r.stdout.splitlines() if l.startswith("✗") and "_bench" in l]   # 临时仓库缺 project.yaml / 旧证据是环境问题，只看新写的
    assert not bad and "B4 证据" in r.stdout, r.stdout
