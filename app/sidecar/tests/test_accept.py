import json, math, pathlib
from dzbench.accept import accept_eval

V = json.loads((pathlib.Path(__file__).parent / "accept_vectors.json").read_text(encoding="utf-8"))


def near(a, b):
    return (not math.isfinite(a)) if b is None else abs(a - b) < 1e-6


def test_vectors():
    for c in V["cases"]:
        r, x = accept_eval(c["t"], c["y"], c["sp"], c["spec"]), c["expect"]
        assert r["pass"] == x["pass"] and len(r["segs"]) == x["segs"], (c["name"], r["why"])
        assert near(r["total"], x["total"]) and near(r["worst_err"], x["worst_err"]), (c["name"], r["total"], r["worst_err"])
