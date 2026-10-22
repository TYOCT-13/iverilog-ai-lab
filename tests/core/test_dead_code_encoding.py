"""Static inspection honors Python source encodings without skipping checks."""
from scripts import check_dead_code


def test_valid_utf8_bom_source_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(check_dead_code, "ROOT", tmp_path)
    source = tmp_path / "valid.py"
    source.write_text("def value():\n    return 1\n", encoding="utf-8-sig")
    assert check_dead_code.scan_file(source) == []


def test_utf8_bom_does_not_hide_unreachable_statements(tmp_path, monkeypatch):
    monkeypatch.setattr(check_dead_code, "ROOT", tmp_path)
    source = tmp_path / "invalid.py"
    source.write_text("def value():\n    return 1\n    print('unreachable')\n", encoding="utf-8-sig")
    findings = check_dead_code.scan_file(source)
    assert any("永远不会执行" in finding for finding in findings)
    assert not any("语法错误" in finding for finding in findings)
