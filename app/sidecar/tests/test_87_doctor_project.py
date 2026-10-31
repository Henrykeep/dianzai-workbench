"""#87：doctor 按打开的项目查；缺器件包只是 warn、只挡烧录；STM32 项目和未开项目都不出 missing_deps。"""
import json
import pathlib

from dzbench import doctor, progress

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _no_missing_deps(items):
    fails = [d["name"] for d in items if d.get("level") == "fail" and d["id"] in ("pack", "target", "config")]
    assert fails == []
    assert not any(b["code"] == "missing_deps" for b in progress.blockers({"deps_missing": fails}))


def test_root_dzbench_has_no_hardcoded_target_or_elf():
    cfg = json.loads((ROOT / "dzbench.json").read_text("utf-8"))
    assert "target" not in (cfg.get("flash") or {})
    assert "elf" not in (cfg.get("build") or {})


def test_stm32_project_no_missing_deps(tmp_path):
    (tmp_path / "scheme.yaml").write_text("mcu: stm32f407vet6\n", "utf-8")
    items = doctor.run(str(ROOT), probes=[], project=str(tmp_path))
    assert doctor.project_chip(str(tmp_path)) == "stm32f407vet6"
    assert not any(d["id"] == "pack" for d in items)
    _no_missing_deps(items)


def test_no_project_open_no_missing_deps():
    items = doctor.run(str(ROOT), probes=[], project=None)
    assert not any(d["id"] == "pack" for d in items)
    _no_missing_deps(items)


def test_mspm0_missing_pack_is_warn_flash_only(tmp_path, monkeypatch):
    (tmp_path / "scheme.yaml").write_text("mcu: mspm0g3507\n", "utf-8")
    monkeypatch.setattr(doctor, "find_pack", lambda t: None)
    items = doctor.run(str(ROOT), probes=[], project=str(tmp_path))
    pack = next(d for d in items if d["id"] == "pack")
    assert pack["level"] == "warn" and pack["blocks"] == ["flash"]
