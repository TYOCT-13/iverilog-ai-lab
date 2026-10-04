"""Freeze the three historical external modules; refuse changed bytes or existing outputs.

Use --local-root for offline copies of the historical cache, or --fetch for network
retrieval. UART's historical ref was master: SHA256, not that mutable ref, is the
acceptance criterion. This is a development replay set, not an independent holdout.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "uart_rx": {"repository": "alexforencich/verilog-uart", "ref": "master",
        "path": "rtl/uart_rx.v", "sha256": "e686104e5ff2d25fa1504e8d08259cef508f2ec9c9e8cfa63364f3fcb39b9f5c",
        "legacy_local": ".iverilog-ai/external/verilog-uart-master/uart_rx.v"},
    "uart_tx": {"repository": "alexforencich/verilog-uart", "ref": "master",
        "path": "rtl/uart_tx.v", "sha256": "e9559ddebf124f8fbface06bf7091296baa78c7acab95a36b40a919663349d34",
        "legacy_local": ".iverilog-ai/external/verilog-uart-master/uart_tx.v"},
    "priority_encoder": {"repository": "alexforencich/verilog-axi",
        "ref": "516bd5dadc3365b7f9e225d2af8fe0b8d804fe53", "path": "rtl/priority_encoder.v",
        "sha256": "df28220d95b47df349a72803a9751aad331eb8e1435416e8686d00572a974dd5",
        "legacy_local": ".iverilog-ai/upstream-cache/verilog-axi-516bd5dadc33/rtl/priority_encoder.v"},
}


def freeze(output: Path, local_root: Path | None) -> Path:
    if output.exists():
        raise FileExistsError(output)
    payloads = {}
    records = {}
    for name, item in SOURCES.items():
        url = f"https://raw.githubusercontent.com/{item['repository']}/{item['ref']}/{item['path']}"
        if local_root is not None:
            data = (local_root / item["legacy_local"]).read_bytes()
        else:
            request = urllib.request.Request(url, headers={"User-Agent": "icarus-external-replay/1"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"{name}: source hash differs from historical frozen input")
        payloads[name] = data
        records[name] = {**item, "local": f"{name}.v", "url": url, "spdx": "MIT",
                         "acquisition": "local_copy" if local_root else "network_hash_verified",
                         "independent_holdout": False}
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        (output / f"{name}.v").write_bytes(data)
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "external-inputs-v1", "modules": records},
                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--local-root", type=Path)
    group.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(freeze(args.output_dir.resolve(), args.local_root))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
