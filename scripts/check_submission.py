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

#: 仓库里**允许**保留占位符的文件——它们是"必须由人替换"的清单本身。
_PLACEHOLDER_ALLOWLIST = {
    "CHANGELOG.md",
    "docs/delivery_review.md",
    "docs/competition/award_report_playbook.md",
    "docs/competition/reference_report_analysis.md",
    "scripts/check_submission.py",
}

#: 会被误当成真实链接的占位符（RFC 2606 保留域）。
#:
#: 刻意**不**扫 `<你的文件.v>` 这类尖括号模板：那是文档里的约定写法（教读者替换），
#: 把它们报成问题只会训练人忽略这个门禁。测试夹具里的 example.invalid 同理——
#: 所以扫描范围限定在"会随作品交出去的那一层"（见 `_SHIPPED_SURFACE`）。
_PLACEHOLDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("example.invalid 保留域", re.compile(r"example\.invalid")),
    ("example.com 保留域", re.compile(r"https?://(?:www\.)?example\.com(?:/|\b)")),
    ("TODO/FIXME 待办", re.compile(r"\b(?:TODO|FIXME)\b")),
)

#: 一行里带这个标记就跳过（用于"这里刻意保留占位符，并已写明原因"的场合）。
_ALLOW_MARKER = "allow-placeholder"

#: "会交出去"的那一层：根目录的元数据与协作文件，加上参赛材料。
#: 仓库内部实现（src/ui/tests/scripts）不扫——那里的占位符是夹具与示例，不是交付物。
_SHIPPED_SURFACE = (
    "CITATION.cff",
    "README.md",
    "pyproject.toml",
    "action.yml",
    "NOTICE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "THIRD_PARTY.md",
    "PROJECT_SCOPE.md",
)
_SHIPPED_DIRS = ("docs/competition",)


#: 正文结束标记：出现这个字符串的页面**及其之后**算附录，不计入正页数上限。
#:
#: 为什么需要它：竞赛规则是"**正文**建议 15 页以内，附录按需提供"。一份 PDF 里正文与附录
#: 是连着的，按总页数判会误伤——把有价值的复盘表、明细表全砍掉只为凑页数，反而降低质量。
#: 与其砍内容，不如让"正文到哪儿结束"变成**文件里写明的、可机械检查的**事实。
DEFAULT_BODY_END_MARKER = "以下为附录"


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


def check_pdf(
    path: Path,
    kind: str,
    forbidden: tuple[str, ...],
    report: Report,
    *,
    body_end_marker: str | None = None,
    fail_on_page_overrun: bool = False,
) -> dict:
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
    # 正文页数：**结束标记所在页之前**的页数。配合 Markdown 里的 `<!-- pagebreak -->`，
    # 正文与附录各自从整页开始，"正文到哪结束"就是一个写在文件里的、可机械检查的事实。
    body_pages = pages
    if body_end_marker:
        found = False
        for index, page in enumerate(doc):
            if body_end_marker in page.get_text("text"):
                body_pages = index
                found = True
                break
        if not found:
            report.add(
                "warning",
                "pages/no-body-marker",
                f"{path.name} 里没有找到正文结束标记「{body_end_marker}」，"
                f"因此按总页数 {pages} 判定——附录会被一起算进页数上限",
            )
    if limits.max_pages is not None:
        # **页数超限是 warning，不是 error。** 规则原文是"正文**建议**控制在 15 页以内，
        # 附录按需提供；**不以报告篇幅、图片数量或材料数量作为评分依据**"——也就是说它是一条
        # 建议，不是一条硬约束，硬约束是体积（≤10MB）与匿名性。
        #
        # 早期版本把它当 error，代价是我们为了凑页数把消融实验、事故复盘、测试条件表一路砍
        # 到附录里，甚至打算删掉对我们不利的结论。**为一个明确声明"不作为评分依据"的建议
        # 去削弱证据，比超出两页糟得多。** 想按硬约束执行的人可以显式加
        # `--fail-on-page-overrun`。
        if body_pages > limits.max_pages:
            report.add(
                "warning" if not fail_on_page_overrun else "error",
                "pages/over-recommended",
                f"{path.name} 正文 {body_pages} 页（总 {pages} 页），超出大纲建议的 "
                f"{limits.max_pages} 页——**建议值，不是硬约束**；请确认这是有意的取舍",
            )
        elif body_pages < limits.max_pages and kind == "report":
            report.add(
                "info",
                "pages/room-left",
                f"{path.name} 正文 {body_pages} 页（总 {pages} 页），距 {limits.max_pages} 页建议值还空 "
                f"{limits.max_pages - body_pages} 页",
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
    return {"file": str(path), "pages": pages, "body_pages": body_pages, "bytes": size}


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


def _shipped_files(root: Path) -> list[Path]:
    """列出"会随作品交出去"的文本文件（根元数据 + 参赛材料目录）。"""

    files: list[Path] = [root / name for name in _SHIPPED_SURFACE]
    for directory in _SHIPPED_DIRS:
        base = root / directory
        if base.is_dir():
            files.extend(sorted(base.rglob("*.md")))
    return [item for item in files if item.is_file()]


def check_repo(path: Path, report: Report) -> dict:
    """扫"会交出去的那一层"，找忘了替换的占位符。

    为什么值得做：`CITATION.cff` 里的 `repository-code` 在仓库转公开前只能是占位符，
    而"参赛期间私有、之后再填"这类事最容易在提交当天忘掉。占位符本身没错，
    **静默带走**才是问题——所以这里把它变成一条会挡住提交的 error。

    扫描范围刻意很窄（见 `_SHIPPED_SURFACE`）：测试夹具和文档模板里的 `example.invalid`
    是有意为之，把它们报成问题只会让人忽略这个门禁。确实需要保留的，在那一行加
    `allow-placeholder` 并写明理由。
    """

    scanned = hits = 0
    for candidate in _shipped_files(path):
        relative = candidate.relative_to(path).as_posix()
        if relative in _PLACEHOLDER_ALLOWLIST:
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        for number, line in enumerate(lines, start=1):
            if _ALLOW_MARKER in line:
                continue
            for label, pattern in _PLACEHOLDER_PATTERNS:
                if pattern.search(line):
                    report.add(
                        "error",
                        "placeholder/unresolved",
                        f"{relative}:{number} 还留着占位符「{label}」：{line.strip()[:88]}",
                    )
                    hits += 1
    report.add(
        "info",
        "placeholder/scanned",
        f"占位符扫描：{scanned} 个交付面文本文件，命中 {hits} 处",
    )
    return {"repo": str(path), "files_scanned": scanned, "placeholders": hits}


def check(
    path: Path,
    kind: str,
    forbidden: tuple[str, ...],
    report: Report,
    *,
    body_end_marker: str | None = None,
    fail_on_page_overrun: bool = False,
) -> dict | None:
    if not path.is_file():
        report.add("error", "file/missing", f"{path} 不存在")
        return None
    if path.suffix.lower() in VIDEO_SUFFIXES:
        return check_video(path, report)
    if path.suffix.lower() != ".pdf":
        report.add("warning", "file/unknown-type", f"{path.name} 不是 PDF，跳过页数与元数据检查")
        return None
    return check_pdf(
        path, kind, forbidden, report,
        body_end_marker=body_end_marker,
        fail_on_page_overrun=fail_on_page_overrun,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="参赛材料体检（匿名性 / 页数 / 体积 / 元数据）")
    parser.add_argument("paths", nargs="+", help="要检查的提交材料，或 `--repo` 的仓库路径")
    parser.add_argument(
        "--repo",
        action="store_true",
        help="把 paths 当成仓库根目录：扫文本文件里「忘了替换」的占位符与链接",
    )
    parser.add_argument("--kind", choices=sorted(KIND_LIMITS), default="report", help="材料类型，决定页数与体积上限")
    parser.add_argument("--max-pages", type=int, default=None, help="覆盖该类型的页数上限")
    parser.add_argument(
        "--forbidden",
        default=None,
        help="额外的敏感词，逗号分隔（会与默认词表合并）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    parser.add_argument(
        "--body-end-marker",
        default=DEFAULT_BODY_END_MARKER,
        help=f"正文结束标记：该标记之后的页面算附录、不计入页数上限（默认「{DEFAULT_BODY_END_MARKER}」）；传空串则按总页数判",
    )
    parser.add_argument(
        "--fail-on-page-overrun",
        action="store_true",
        help="把「正文超出建议页数」当成 error。默认只是 warning——大纲里写的是"
             "「建议」且明确不以篇幅评分，为一个建议值挡住提交是加错了约束",
    )
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
        if args.repo:
            if not path.is_dir():
                report.add("error", "file/missing", f"{path} 不是目录，--repo 需要一个仓库根目录")
                continue
            checked.append(check_repo(path, report))
            continue
        info = check(
            path, args.kind, forbidden, report,
            body_end_marker=args.body_end_marker or None,
            fail_on_page_overrun=args.fail_on_page_overrun,
        )
        if info:
            checked.append(info)

    if args.json:
        print(json.dumps({**report.to_dict(), "checked": checked}, ensure_ascii=False, indent=2))
    else:
        for item in checked:
            if "repo" in item:
                print(f"已扫描仓库 {item['repo']}（{item['files_scanned']} 个文本文件，命中 {item['placeholders']} 处占位符）")
                continue
            summary = f"已检查 {item['file']}"
            if "pages" in item:
                body = item.get("body_pages")
                extra = f"，正文 {body} 页" if body is not None and body != item["pages"] else ""
                summary += f"（共 {item['pages']} 页{extra}，{item['bytes'] / 1024:.0f} KB）"
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
