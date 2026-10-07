"""Clear anonymous PPTX metadata on a new candidate before finalization."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

source, target = map(Path, sys.argv[1:3])
assert source.is_file() and not target.exists()
with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "x") as output:
    assert len(original.namelist()) == len(set(original.namelist()))
    for item in original.infolist():
        data = original.read(item.filename)
        if item.filename == "docProps/core.xml":
            root = ET.fromstring(data)
            for child in list(root):
                root.remove(child)
            data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        elif item.filename == "docProps/app.xml":
            root = ET.fromstring(data)
            for child in root:
                if child.tag.rsplit("}", 1)[-1] in {"Company", "Manager"}:
                    child.text = ""
            data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        output.writestr(item, data)
print("Anonymous candidate metadata cleared before finalization")

