"""提交材料体检：把"规则里写死的硬约束"变成可执行的检查。

为什么需要它：规则第（九）条要求技术报告、演示视频、答辩 PPT 中不得出现学校名称、
学校 LOGO 与指导教师信息；技术报告正文建议 15 页以内、PDF 不超过 10MB；演示视频
3–5 分钟、不超过 300MB。这些全部是可以机械检查的，靠人眼逐页看必然会漏。

真实教训（来自 `docs/competition/reference_report_analysis.md`）：一份往届国二报告的
正文已经匿名成"成员A/B/C"，**但 PDF 文档属性里写着作者真名**，producer 还写着具体的
操作系统版本。匿名性因此被削弱——这种事只有脚本能稳定发现。

用法：
    python scripts/check_submission.py docs/competition/technical_report.pdf
    python scripts/check_submission.py --kind report --max-pages 15 *.pdf
    python scripts/check_submission.py --kind video demo.mp4
退出码：0 = 全部通过（可以带 warning），1 = 有 error。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF

#: 参赛材料里出现这些词就要人工确认（默认词表偏保守，命中不等于一定违规）。
DEFAULT_FORBIDDEN = (
    "大学",
    "学院",
    "学校",
    "指导教师",
    "指导老师",
    "导师",
    "辅导员",
    "实验室",
    "课题组",
    "附属医院",
)

#: 元数据里明确不该出现内容的字段。
REQUIRED_BLANK_METADATA = ("author", "subject", "keywords")

#: 元数据字段即使为空也要打印出来供人工确认（导出工具会往里写东西）。
REPORT_METADATA = ("title", "author", "subject", "keywords", "creator", "producer")

@dataclass(frozen=True)
class KindLimit:
    """一类提交材料的硬上限。`max_pages=None` 表示这类材料不限页数（如视频）。"""

    max_pages: int | None
    max_bytes: int


KIND_LIMITS: dict[str, KindLimit] = {
    "report": KindLimit(max_pages=15, max_bytes=10 * 1024 * 1024),
    "ppt": KindLimit(max_pages=40, max_bytes=100 * 1024 * 1024),
    "video": KindLimit(max_pages=None, max_bytes=300 * 1024 * 1024),
}

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".avi")


@dataclass
class Finding:
    """一条体检结论。level 只用 error / warning / info。"""

    level: str
    code: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, code: str, message: str) -> None:
        self.findings.append(Finding(level, code, message))

    @property
    def errors(self) -> list[Finding]:
        return [item for item in self.findings if item.level == "error"]

    def to_dict(self) -> dict:
        return {
            "ok": not self.errors,
            "findings": [item.__dict__ for item in self.findings],
        }


def _scan_text(text: str, forbidden: Iterable[str], where: str, report: Report) -> None:
    for word in forbidden:
        for match in re.finditer(re.escape(word), text):
            start = max(0, match.start() - 18)
            end = min(len(text), match.end() + 18)
            snippet = text[start:end].replace("\n", " ")
            report.add(
                "warning",
                "anonymity/keyword",
                f"{where} 命中「{word}」：…{snippet}…（需人工确认是否构成披露）",
            )


def check_pdf(path: Path, kind: str, forbidden: tuple[str, ...], report: Report) -> dict:
    limits = KIND_LIMITS[kind]
    size = path.stat().st_size
    if size > limits.max_bytes:
        report.add(
            "error",
            "size/too-large",
            f"{path.name} 为 {size / 1024 / 1024:.1f} MB，超过 {limits.max_bytes / 1024 / 1024:.0f} MB",
        )

    doc = fitz.open(path)
    pages = doc.page_count
    if limits.max_pages is not None:
        if pages > limits.max_pages:
            report.add(
                "error",
                "pages/too-many",
                f"{path.name} 共 {pages} 页，超过正文建议上限 {limits.max_pages} 页",
            )
        elif pages < limits.max_pages and kind == "report":
            report.add(
                "info",
                "pages/room-left",
                f"{path.name} 只有 {pages} 页，距 {limits.max_pages} 页上限还空 {limits.max_pages - pages} 页",
            )

    metadata = {key: (value or "").strip() for key, value in (doc.metadata or {}).items()}
    for key in REQUIRED_BLANK_METADATA:
        if metadata.get(key):
            report.add(
                "warning",
                "metadata/identity",
                f"{path.name} 元数据 {key} 非空：{metadata[key]!r}——导出工具可能把作者真名写进去了",
            )
    report.add(
        "info",
        "metadata/dump",
        f"{path.name} 元数据：" + json.dumps({k: metadata.get(k, "") for k in REPORT_METADATA}, ensure_ascii=False),
    )

    for index, page in enumerate(doc):
        _scan_text(page.get_text("text"), forbidden, f"{path.name} 第 {index + 1} 页", report)
    doc.close()
    return {"file": str(path), "pages": pages, "bytes": size}


def check_video(path: Path, report: Report) -> dict:
    limit = KIND_LIMITS["video"].max_bytes
    size = path.stat().st_size
    if size > limit:
        report.add("error", "size/too-large", f"{path.name} 为 {size / 1024 / 1024:.0f} MB，超过 {limit / 1024 / 1024:.0f} MB")
    report.add(
        "info",
        "video/duration-manual",
        f"{path.name} 时长需人工确认为 3–5 分钟（脚本不解析容器时长）",
    )
    return {"file": str(path), "bytes": size}


def check(path: Path, kind: str, forbidden: tuple[str, ...], report: Report) -> dict | None:
    if not path.is_file():
        report.add("error", "file/missing", f"{path} 不存在")
        return None
    if path.suffix.lower() in VIDEO_SUFFIXES:
        return check_video(path, report)
    if path.suffix.lower() != ".pdf":
        report.add("warning", "file/unknown-type", f"{path.name} 不是 PDF，跳过页数与元数据检查")
        return None
    return check_pdf(path, kind, forbidden, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="参赛材料体检（匿名性 / 页数 / 体积 / 元数据）")
    parser.add_argument("paths", nargs="+", help="要检查的提交材料")
    parser.add_argument("--kind", choices=sorted(KIND_LIMITS), default="report", help="材料类型，决定页数与体积上限")
    parser.add_argument("--max-pages", type=int, default=None, help="覆盖该类型的页数上限")
    parser.add_argument(
        "--forbidden",
        default=None,
        help="额外的敏感词，逗号分隔（会与默认词表合并）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)

    if args.max_pages is not None:
        current = KIND_LIMITS[args.kind]
        KIND_LIMITS[args.kind] = KindLimit(max_pages=args.max_pages, max_bytes=current.max_bytes)

    forbidden = tuple(DEFAULT_FORBIDDEN) + tuple(
        item.strip() for item in (args.forbidden or "").split(",") if item.strip()
    )

    report = Report()
    checked = []
    for raw in args.paths:
        path = Path(raw)
        info = check(path, args.kind, forbidden, report)
        if info:
            checked.append(info)

    if args.json:
        print(json.dumps({**report.to_dict(), "checked": checked}, ensure_ascii=False, indent=2))
    else:
        for item in checked:
            summary = f"已检查 {item['file']}"
            if "pages" in item:
                summary += f"（{item['pages']} 页，{item['bytes'] / 1024:.0f} KB）"
            print(summary)
        icon = {"error": "错误", "warning": "警告", "info": "提示"}
        for finding in report.findings:
            print(f"[{icon[finding.level]}] {finding.code}: {finding.message}")
        errors = len(report.errors)
        warnings = sum(1 for item in report.findings if item.level == "warning")
        print(f"\n结果：{errors} error / {warnings} warning")
        if errors:
            print("提交前必须修掉上面的 error。", file=sys.stderr)

    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
