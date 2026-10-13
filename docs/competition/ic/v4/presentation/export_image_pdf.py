"""Export the reviewed artifact-tool slide PNGs as a new anonymous 16:9 PDF."""
from pathlib import Path
import hashlib
import json
import sys

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

render_dir, output_path, receipt_path = map(Path, sys.argv[1:4])
expected_count = int(sys.argv[4]) if len(sys.argv) > 4 else 20
images = sorted(render_dir.glob("slide-*.png"))
if len(images) != expected_count:
    raise ValueError(f"Expected {expected_count} reviewed slides, got {len(images)}")
if output_path.exists() or receipt_path.exists():
    raise FileExistsError("Preserve existing outputs and receipts")
temporary = receipt_path.with_suffix(".reportlab.pdf")
if temporary.exists():
    raise FileExistsError(temporary)
canvas = Canvas(str(temporary), pagesize=(960, 540), pageCompression=1)
for setter in (canvas.setAuthor, canvas.setTitle, canvas.setSubject, canvas.setCreator, canvas.setKeywords):
    setter("")
for image_path in images:
    canvas.drawImage(ImageReader(str(image_path)), 0, 0, width=960, height=540)
    canvas.showPage()
canvas.save()
reader = PdfReader(temporary)
writer = PdfWriter()
for page in reader.pages:
    writer.add_page(page)
writer._info = None
writer._root_object.pop(NameObject("/Metadata"), None)
with output_path.open("xb") as stream:
    writer.write(stream)
final = PdfReader(output_path)
assert len(final.pages) == expected_count
assert not final.metadata
assert "/Metadata" not in final.trailer["/Root"]
assert all(tuple(float(v) for v in page.mediabox) == (0.0, 0.0, 960.0, 540.0) for page in final.pages)
receipt = {
    "schema": "icarus-ic-v4-defense-image-pdf-v1",
    "output": str(output_path.resolve()),
    "mode": "image_only_from_final_artifact_tool_render",
    "slides": expected_count,
    "size_bytes": output_path.stat().st_size,
    "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    "canvas_points": [960, 540],
    "editable_source": "PPTX",
    "source_pngs": [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in images],
    "native_PowerPoint_validation": False,
}
with receipt_path.open("x", encoding="utf-8") as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print(json.dumps({"pdf": str(output_path), "slides": expected_count, "bytes": output_path.stat().st_size}))
