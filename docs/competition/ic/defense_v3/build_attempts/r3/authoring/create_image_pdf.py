"""Export a new image-only PDF from every final PPTX slide PNG."""
from pathlib import Path
import sys
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

render, target = map(Path, sys.argv[1:3])
images = sorted(render.glob("slide-*.png"))
assert len(images) == 12 and not target.exists()
temporary = target.with_name(target.stem + ".reportlab-original.pdf")
assert not temporary.exists()
canvas = Canvas(str(temporary), pagesize=(960, 540), pageCompression=1)
for setter in (canvas.setAuthor, canvas.setTitle, canvas.setSubject, canvas.setCreator, canvas.setKeywords):
    setter("")
for image in images:
    canvas.drawImage(ImageReader(str(image)), 0, 0, width=960, height=540)
    canvas.showPage()
canvas.save()
reader, writer = PdfReader(temporary), PdfWriter()
for page in reader.pages:
    writer.add_page(page)
writer._info = None
writer._root_object.pop(NameObject("/Metadata"), None)
with target.open("xb") as stream:
    writer.write(stream)
final = PdfReader(target)
assert len(final.pages) == len(images) and not final.metadata
assert "/Metadata" not in final.trailer["/Root"]
print("Image-only PDF exported: 12 pages, no document metadata")

