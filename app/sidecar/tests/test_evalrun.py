"""评测运行器本身的离线测试（不连真大模型）：没 Key 退出 2、报告生成、退回离线判无效。"""
import pytest
import json

from dzbench.agent import evalrun


def fake_sim(mode):
    def run(port, llm=None, cases=None, **_):
        return [{"id": c["id"], "ok": i % 2 == 0, "why": [] if i % 2 == 0 else ["应调用 x"], "calls": [], "text": "", "mode": mode}
                for i, c in enumerate(cases)]
    return run


def test_no_key_exits_2(home, monkeypatch, capsys):
    monkeypatch.delenv("DZBENCH_API_KEY", raising=False)
    assert evalrun.main(["--repeat", "1"]) == 2
    assert "Key" in capsys.readouterr().err


def test_report_written_and_scored(home, tmp_path):
    rc = evalrun.main(["--repeat", "2", "--ports", "sim:a", "--out", str(tmp_path)], llm=object(), run_sim=fake_sim("llm"))
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert rc == 1 and rep["valid"] and rep["total"] == 2 * len(rep["cases"])
    assert all(c["total"] == 2 for c in rep["cases"])
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "总分" in md and "api_key" not in json.dumps(rep)


def test_fallback_to_offline_is_invalid(home, tmp_path):
    rc = evalrun.main(["--repeat", "1", "--ports", "sim:a", "--out", str(tmp_path)], llm=object(), run_sim=fake_sim("offline"))
    assert rc == 2 and "不能当大模型成绩" in (tmp_path / "report.md").read_text(encoding="utf-8")


@pytest.mark.needs_sim
def test_offline_baseline_real_sim(home, tmp_path):
    rc = evalrun.main(["--offline", "--repeat", "1", "--ports", "sim:car_2wd", "--out", str(tmp_path)])
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert rc in (0, 1) and rep["valid"] and rep["total"] == len(rep["cases"])
