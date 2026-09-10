"""Run the deterministic RTL static quality review."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from iverilog_ai.core.static_review import review_rtl_file, render_static_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtl", required=True)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    result = review_rtl_file(args.rtl)
    output = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path(args.rtl).expanduser().resolve().parent / ".iverilog-ai-review"
    output.mkdir(parents=True, exist_ok=True)
    (output / "rtl_quality_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "rtl_quality_report.md").write_text(render_static_markdown(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "quality_score": result["quality_score"], "findings": result["finding_count"], "output_dir": str(output)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
