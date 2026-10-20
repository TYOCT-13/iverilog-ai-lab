"""Retain original chart workbooks lost by PPTX import/export, without changing chart data."""
import hashlib
import json
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
for prefix in ("c", "r"):
    ET.register_namespace(prefix, NS[prefix])

def rels(part):
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")

def target(part, relative):
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), relative)).lstrip("/")

def chart_for_slide(package, owner):
    slide = f"ppt/slides/slide{owner}.xml"
    node = ET.fromstring(package[slide]).find(".//c:chart", NS)
    assert node is not None
    rid = node.attrib["{" + NS["r"] + "}id"]
    relationships = ET.fromstring(package[rels(slide)])
    relationship = next(r for r in relationships if r.attrib["Id"] == rid)
    return target(slide, relationship.attrib["Target"])

def series_data(root):
    return [([float(p.text) for p in s.findall("c:val//c:pt/c:v", NS)],
             [p.text for p in s.findall("c:cat//c:pt/c:v", NS)])
            for s in root.findall(".//c:ser", NS)]

source, candidate, output, receipt_path = map(Path, sys.argv[1:])
with zipfile.ZipFile(source) as z:
    original = {n: z.read(n) for n in z.namelist()}
with zipfile.ZipFile(candidate) as z:
    data = {n: z.read(n) for n in z.namelist()}
receipt = []
for owner in (11, 12):
    old_chart, chart = chart_for_slide(original, owner), chart_for_slide(data, owner)
    old_root, chart_root = ET.fromstring(original[old_chart]), ET.fromstring(data[chart])
    assert series_data(old_root) == series_data(chart_root), "Imported chart data changed"
    external = old_root.find("c:externalData", NS)
    assert external is not None
    old_relationships = ET.fromstring(original[rels(old_chart)])
    relation = next(r for r in old_relationships if r.attrib["Id"] == external.attrib["{" + NS["r"] + "}id"])
    old_book = target(old_chart, relation.attrib["Target"])
    book_bytes = original[old_book]
    book = f"ppt/embeddings/retained-source-slide-{owner}.xlsx"
    data[book] = book_bytes
    chart_rels = ET.fromstring(data[rels(chart)]) if rels(chart) in data else ET.Element("{" + NS["rel"] + "}Relationships")
    for item in list(chart_rels):
        if item.attrib["Type"].endswith("/package"):
            chart_rels.remove(item)
    rid = "rIdRetainedSourceWorkbook"
    ET.SubElement(chart_rels, "{" + NS["rel"] + "}Relationship", {
        "Id": rid, "Type": relation.attrib["Type"],
        "Target": posixpath.relpath(book, posixpath.dirname(chart))})
    new_external = chart_root.find("c:externalData", NS)
    if new_external is None:
        new_external = ET.SubElement(chart_root, "{" + NS["c"] + "}externalData")
    new_external.set("{" + NS["r"] + "}id", rid)
    data[chart] = ET.tostring(chart_root, encoding="utf-8", xml_declaration=True)
    ET.register_namespace("", NS["rel"])
    data[rels(chart)] = ET.tostring(chart_rels, encoding="utf-8", xml_declaration=True)
    receipt.append({"slide": owner, "source_workbook": old_book, "retained_workbook": book,
                    "sha256": hashlib.sha256(book_bytes).hexdigest(), "chart_data_equal": True})
types = ET.fromstring(data["[Content_Types].xml"])
content_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
if not any(item.attrib.get("Extension") == "xlsx" for item in types):
    ET.SubElement(types, "{" + content_ns + "}Default", {"Extension": "xlsx", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
ET.register_namespace("", content_ns)
data["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8", xml_declaration=True)
assert not output.exists()
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
    for name, body in data.items():
        z.writestr(name, body)
receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print("Retained both source workbooks; original chart data unchanged")
