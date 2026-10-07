"""Artifact structure and PDF rendering QA only; no experiment is rerun."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
import fitz
from PIL import Image, ImageChops
from pypdf import PdfReader

build, pptx, pdf = map(Path, sys.argv[1:4])
root = build.parents[2]
def item(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw)}
ns={"p":"http://schemas.openxmlformats.org/presentationml/2006/main",
    "a":"http://schemas.openxmlformats.org/drawingml/2006/main",
    "c":"http://schemas.openxmlformats.org/drawingml/2006/chart"}
tables, charts, fonts = [], [], Counter()
with zipfile.ZipFile(pptx) as package:
    names = package.namelist()
    assert package.testzip() is None and len(names) == len(set(names))
    slides = sorted([name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)],
                    key=lambda name: int(re.search(r"slide(\d+)", name)[1]))
    assert len(slides) == 12
    for number, name in enumerate(slides, 1):
        document=ET.fromstring(package.read(name))
        if document.findall(".//a:tbl", ns):
            tables.append(number)
        if document.findall(".//c:chart", ns):
            charts.append(number)
        for font in document.findall(".//a:latin",ns)+document.findall(".//a:ea",ns):
            if font.get("typeface"):
                fonts[font.get("typeface")] += 1
    chart_files = [name for name in names if re.fullmatch(r"ppt/charts/chart\d+\.xml",name)]
    workbooks = [name for name in names if name.startswith("ppt/embeddings/") and name.endswith(".xlsx")]
    assert len(chart_files) == 3 and len(workbooks) == 3
    assert tables == [4,5,7,8,9,10,12] and charts == [6,11]
    core=ET.fromstring(package.read("docProps/core.xml"))
    assert not list(core), "PPTX anonymous core metadata"
    for name in [name for name in names if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")]:
        text="".join(ET.fromstring(package.read(name)).itertext())
        assert "TYOCT" not in text and "C:/Users/" not in text
reader=PdfReader(pdf)
assert len(reader.pages)==12 and not reader.metadata
output=build/"pdf-render";output.mkdir()
observations=[]
with fitz.open(pdf) as document:
    for index, page in enumerate(document):
        pix=page.get_pixmap(matrix=fitz.Matrix(2560/960,1440/540), alpha=False)
        destination=output/f"slide-{index+1:02d}.png"
        pix.save(destination)
        source=build/"final-render"/destination.name
        with Image.open(source) as src, Image.open(destination) as dst:
            left,right=src.convert("RGB"),dst.convert("RGB")
            assert left.size==right.size==(2560,1440)
            difference=ImageChops.difference(left,right)
            exact=difference.getbbox() is None
            maximum=max(channel[1] for channel in difference.getextrema())
        observations.append({"slide":index+1,"pptx_slide_png":item(source),"pdf_page_png":item(destination),
            "pixel_identical":exact,"maximum_channel_difference":maximum})
report={"schema":"icarus-defense-v3-artifact-machine-qa-v1",
        "slides":12,"PPTX":item(pptx),"PDF":item(pdf),"PDF_image_only":True,
        "PDF_document_metadata_empty":True,"PPTX_core_metadata_empty":True,
        "native_chart_files":len(chart_files),"embedded_literal_workbooks":len(workbooks),
        "native_chart_owner_slides":charts,"native_table_owner_slides":tables,"font_counts":dict(fonts),
        "native_Office_open_or_edit_test":False,"google_slides_test":False,
        "visual_inspection_pending":True,"renders":observations,
        "API_requests":0,"credential_file_reads":0,"DUT_executions":0,
        "engineering_tests_reexecuted":0}
destination=build/"artifact_machine_qa.json"
with destination.open("x",encoding="utf-8",newline="\n") as stream:
    json.dump(report,stream,ensure_ascii=False,indent=2);stream.write("\n")
print(json.dumps({key:report[key] for key in ("slides","native_chart_files","embedded_literal_workbooks",
    "native_table_owner_slides","PPTX","PDF","PDF_document_metadata_empty")},ensure_ascii=False))

