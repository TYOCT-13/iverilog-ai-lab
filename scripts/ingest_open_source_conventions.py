"""从真实开源 Verilog 项目度量编码与验证约定，生成可追溯的规约包。

用法：

    # 度量并写入默认产物（需要网络；上游按固定提交拉取）
    python scripts/ingest_open_source_conventions.py

    # 只度量已经解包在本地缓存里的源码（完全离线）
    python scripts/ingest_open_source_conventions.py --offline

    # 从上游 API 刷新固定提交号（会改写 conventions 模块里的 ref）
    python scripts/ingest_open_source_conventions.py --refresh-refs

产物：

    data/opensource_conventions.json   机器可读：出处、许可证、每文件 sha256、探针统计
    docs/opensource_conventions.md     人读版：统计表 + 口径说明 + 复现命令

**本脚本不复制上游代码。** 它只记录聚合统计量与每文件的 sha256 指纹，
因此产出的知识资产不含第三方代码，也不触发上游许可证的再分发义务。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from iverilog_ai.core.conventions import (  # noqa: E402
    DEFAULT_SOURCES,
    ConventionSource,
    fetch_source,
    measure_source,
    render_conventions_context,
)

JSON_OUT = ROOT / "data" / "opensource_conventions.json"
DOC_OUT = ROOT / "docs" / "opensource_conventions.md"
# 上游源码缓存放在项目常规的工件目录下（已 gitignore），不随仓库分发。
CACHE_DIR = ROOT / ".iverilog-ai" / "upstream-cache"


def _refresh_refs() -> int:
    """从上游 API 读取默认分支的最新提交，并写回 conventions 模块。"""

    import re
    import urllib.request

    module_path = ROOT / "src" / "iverilog_ai" / "core" / "conventions.py"
    text = module_path.read_text(encoding="utf-8")
    changed = 0
    for source in DEFAULT_SOURCES:
        url = f"https://api.github.com/repos/{source.repository}/commits?per_page=1"
        request = urllib.request.Request(url, headers={"User-Agent": "iverilog-ai-lab-conventions/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            sha = payload[0]["sha"]
        except Exception as exc:  # pragma: no cover - 仅在网络异常时触发
            print(f"  {source.repository}: 读取失败 {type(exc).__name__}: {exc}")
            continue
        if sha == source.ref:
            print(f"  {source.repository}: 已是最新 {sha[:12]}")
            continue
        updated = re.sub(
            rf'(key="{re.escape(source.key)}",\s*\n\s*repository="{re.escape(source.repository)}",\s*\n\s*ref=")[0-9a-f]+(")',
            rf"\g<1>{sha}\g<2>",
            text,
        )
        if updated != text:
            text = updated
            changed += 1
            print(f"  {source.repository}: {source.ref[:12]} -> {sha[:12]}")
    if changed:
        module_path.write_text(text, encoding="utf-8")
    return changed


def _measure(source: ConventionSource, *, offline: bool) -> dict:
    if offline:
        cached = CACHE_DIR / f"{source.key}-{source.ref[:12]}"
        if not cached.is_dir():
            raise SystemExit(
                f"离线模式下找不到缓存目录 {cached.relative_to(ROOT)}；"
                "请先联网跑一次 python scripts/ingest_open_source_conventions.py"
            )
        root = cached
    else:
        root = fetch_source(source, CACHE_DIR)
    measured = measure_source(root)
    return {
        "key": source.key,
        **source.to_dict(),
        "file_count": measured["file_count"],
        "total_bytes": measured["total_bytes"],
        "files": measured["files"],
        "probes": measured["probes"],
    }


def _render_doc(payload: dict) -> str:
    lines = [
        "# 从开源项目实测的编码与验证约定",
        "",
        f"生成时间：{payload['generated_at']}",
        f"生成方式：`python scripts/ingest_open_source_conventions.py`（对固定提交的源码做统计度量）",
        "",
        "## 这份东西是什么，不是什么",
        "",
        "**是**：对真实开源 Verilog 项目的**统计度量**——上游有多少比例的文件采用了某种写法。",
        "产物只含聚合数字与每文件的 sha256 指纹，**不含任何上游源代码**。",
        "",
        "**不是**：不是规范、不是 lint 规则、不参与 PASS/FAIL 判决。",
        "它唯一的作用是给 AI 规划器提供社区惯例背景，让生成的测试计划更贴合真实工程写法。",
        "覆盖率不足的探针会被标成 `weak`，措辞明确写成「上游较少如此，不构成约定」。",
        "",
        "## 度量来源",
        "",
        "| 项目 | 固定提交 | 许可证 | 度量文件数 | 源码字节 | 说明 |",
        "|---|---|---|---:|---:|---|",
    ]
    for source in payload["sources"]:
        lines.append(
            f"| [{source['repository']}](https://github.com/{source['repository']}) "
            f"| `{source['ref'][:12]}` | {source['spdx']} | {source['file_count']} "
            f"| {source['total_bytes']} | {source.get('note', '')} |"
        )
    lines.extend(["", "## 实测统计", ""])
    for source in payload["sources"]:
        lines.extend([f"### {source['repository']}", "", "| 探针 | 命中/总数 | 覆盖率 | 置信度 |", "|---|---:|---:|---|"])
        for probe in source["probes"]:
            lines.append(
                f"| {probe['title']} | {probe['numerator']}/{probe['denominator']} "
                f"| {probe['ratio'] * 100:.0f}% | `{probe['confidence']}` |"
            )
        lines.append("")
    lines.extend(
        [
            "## 复现",
            "",
            "```powershell",
            "python scripts/ingest_open_source_conventions.py            # 联网，按固定提交拉取并度量",
            "python scripts/ingest_open_source_conventions.py --offline  # 复用本地缓存，完全离线",
            "```",
            "",
            "## 许可证与权利边界",
            "",
            "- 本文件与其 JSON 产物由本项目（Apache-2.0）授权；",
            "- 上游项目的权利归属不因本次度量而改变；本项目未复制、未修改、未再分发其代码；",
            "- 上表中的许可证与固定提交号可据以复核度量结果；",
            "- 每文件的 sha256 指纹记录在 JSON 产物里，可验证度量确实针对该提交。",
            "",
            "## 给 AI 规划器的接入方式",
            "",
            "```python",
            "from iverilog_ai.core.conventions import load_conventions, render_conventions_context",
            "context = render_conventions_context(load_conventions(Path('data/opensource_conventions.json')))",
            "```",
            "",
            "生成的片段会随 `plan_tests(...)` 的上下文一起发送。它**不改变判定口径**：",
            "testbench 仍由确定性模板生成，PASS/FAIL 仍只由 Icarus 与结构化断言决定。",
            "",
            "## 给 AI 规划器的实际片段（预览）",
            "",
            "```text",
            payload["prompt_preview"],
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="从开源项目度量编码与验证约定")
    parser.add_argument("--offline", action="store_true", help="只使用本地缓存，不联网")
    parser.add_argument("--refresh-refs", action="store_true", help="从上游 API 刷新固定提交号后退出")
    parser.add_argument("--keep-cache", action="store_true", help="保留解包的上游源码（默认保留，便于离线复跑）")
    args = parser.parse_args()

    if args.refresh_refs:
        print("刷新固定提交号：")
        changed = _refresh_refs()
        print(f"更新 {changed} 个来源")
        return 0

    sources = []
    for source in DEFAULT_SOURCES:
        print(f"度量 {source.repository} @ {source.ref[:12]} ...")
        try:
            measured = _measure(source, offline=args.offline)
        except SystemExit as exc:
            print(f"  {exc}")
            return 2
        print(f"  文件 {measured['file_count']} 个，{measured['total_bytes']} 字节")
        sources.append(measured)

    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generator": "scripts/ingest_open_source_conventions.py",
        "note": "只含聚合统计与文件指纹，不含上游源代码",
        "sources": sources,
    }
    payload["prompt_preview"] = render_conventions_context(payload)

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DOC_OUT.write_text(_render_doc(payload), encoding="utf-8")
    print(f"\n写入 {JSON_OUT.relative_to(ROOT)}（{JSON_OUT.stat().st_size // 1024} KB）")
    print(f"写入 {DOC_OUT.relative_to(ROOT)}")
    print(f"上游源码缓存在 {CACHE_DIR.relative_to(ROOT)}（已 gitignore，不随仓库分发）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
