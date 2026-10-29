"""保护阈值表：protect / protect_fixed 只给界面，不进 schema 哈希（改分类不用重烧）。"""
import importlib.util
import pathlib

import yaml

from dzbench.schema import Schema

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _gen():
    spec = importlib.util.spec_from_file_location("gen_link", ROOT / "tools" / "gen_link.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_protect_not_hashed_and_passed_to_ui(tmp_path):
    g = _gen()
    link = yaml.safe_load((ROOT / "apps/car_2wd/app.yaml").read_text(encoding="utf-8"))["link"]
    s = g.schema(link, link["params"])
    bare = {k: v for k, v in link.items() if k != "protect_fixed"}
    bare_params = [{k: v for k, v in p.items() if k != "protect"} for p in link["params"]]
    assert g.schema(bare, bare_params)["hash"] == s["hash"]
    assert [p.get("protect") for p in s["params"]].count("限幅") == 2
    import json
    f = tmp_path / "link_schema.json"
    f.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    summ = Schema(json.loads(f.read_text(encoding="utf-8")), str(f)).summary()
    assert summ["protect_fixed"][0]["value"] == 500
    assert any(p.get("protect") == "断线停车" for p in summ["params"])
