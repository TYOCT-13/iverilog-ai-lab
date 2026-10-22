"""Browser manual links retain repository targets without creating app routes."""
from ui.manual_links import manual_web_links


def test_manual_links_resolve_files_directories_and_anchors(tmp_path):
    root = tmp_path
    source = root / "docs/manual/start.md"
    source.parent.mkdir(parents=True)
    (root / "docs/setup.md").write_text("setup", encoding="utf-8")
    (root / "CONTRIBUTING.md").write_text("contribute", encoding="utf-8")
    (source.parent / "deep.md").write_text("deep", encoding="utf-8")
    text = "[安装](../setup.md) [贡献](../../CONTRIBUTING.md) [字段](deep.md#results) [目录](.)"
    result = manual_web_links(text, source, root)
    base = "https://github.com/TYOCT-13/iverilog-ai-lab"
    assert f"{base}/blob/main/docs/setup.md" in result
    assert f"{base}/blob/main/CONTRIBUTING.md" in result
    assert f"{base}/blob/main/docs/manual/deep.md#results" in result
    assert f"{base}/tree/main/docs/manual" in result


def test_manual_links_preserve_code_images_external_and_outside_targets(tmp_path):
    source = tmp_path / "docs/start.md"
    source.parent.mkdir()
    (source.parent / "next.md").write_text("next", encoding="utf-8")
    untouched = "[外部](https://example.org) [锚点](#here) ![图](next.md) `[示例](next.md)` [越界](../../outside.md)\n```text\n[原样](next.md)\n```\n"
    assert manual_web_links(untouched, source, tmp_path) == untouched
