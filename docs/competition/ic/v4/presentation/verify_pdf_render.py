"""Verify each PDF page embeds the reviewed pixels and Poppler rendered every page."""
from pathlib import Path
import json
import sys
from PIL import Image
from pypdf import PdfReader

pdf_path, source_dir, render_dir, receipt_path = map(Path, sys.argv[1:5])
expected_count = int(sys.argv[5]) if len(sys.argv) > 5 else 20
reader = PdfReader(pdf_path)
sources = sorted(source_dir.glob("slide-*.png"))
renders = sorted(render_dir.glob("page-*.png"))
assert len(reader.pages) == len(sources) == len(renders) == expected_count
checks = []
for number, (page, source, rendered) in enumerate(zip(reader.pages, sources, renders), 1):
    assert len(page.images) == 1
    with Image.open(source) as source_image:
        source_rgb = source_image.convert("RGB")
        embedded = page.images[0].image.convert("RGB")
        assert embedded.size == source_rgb.size == (2560, 1440)
        assert embedded.tobytes() == source_rgb.tobytes()
    with Image.open(rendered) as rendered_image:
        assert rendered_image.size == (1280, 720)
    checks.append({"slide": number, "embedded_reviewed_pixels_match": True, "poppler_render_size": [1280, 720]})
result = {"schema": "icarus-ic-v4-pdf-render-verification-v1", "slides": expected_count, "all_reviewed_pixels_embedded": True, "all_pages_rendered": True, "checks": checks}
with receipt_path.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print(json.dumps({"slides": expected_count, "embedded_reviewed_pixels_match": True, "poppler_pages": expected_count}))
