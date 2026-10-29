"""doctor 自检 + 多探针不猜。"""
import pytest

from dzbench import doctor
from dzbench.flash import FlashError, choose_probe


def test_choose_probe_never_guesses():
    two = [{"uid": "A1", "desc": "DAPLink"}, {"uid": "B2", "desc": "ST-Link"}]
    with pytest.raises(FlashError) as e:
        choose_probe(None, two)
    assert e.value.code == "multi_probe" and "A1" in e.value.message and "flash.probe" in e.value.fix
    assert choose_probe("B2", two) == "B2"
    with pytest.raises(FlashError) as e:
        choose_probe("C3", two)
    assert e.value.code == "probe_missing"
    assert choose_probe(None, two[:1]) == "A1" and choose_probe(None, []) is None


def test_doctor_items_have_fix_hints(home, tmp_path):
    (tmp_path / "dzbench.json").write_text('{"flash": {"target": "mspm0g3507"}}', encoding="utf-8")
    items = doctor.run(str(tmp_path), which=lambda _: None,
                       probes=[{"uid": "A1", "desc": "x"}, {"uid": "B2", "desc": "y"}])
    by = {i["id"]: i for i in items}
    assert by["arm_gcc"]["level"] == "warn" and "PATH" in by["arm_gcc"]["fix"]
    assert by["probe"]["level"] == "warn" and "flash.probe" in by["probe"]["fix"]
    assert "pack" in by and by["home"]["level"] == "ok"
    assert all(i["fix"] for i in items if i["level"] != "ok"), "每个非 ok 项都要有中文修复提示"
    assert "必须处理" in doctor.render(items) or "没有阻塞项" in doctor.render(items)


def test_doctor_bad_config_is_fail(home, tmp_path):
    (tmp_path / "dzbench.json").write_text("{bad", encoding="utf-8")
    by = {i["id"]: i for i in doctor.run(str(tmp_path), probes=[])}
    assert by["config"]["level"] == "fail" and by["config"]["fix"]
