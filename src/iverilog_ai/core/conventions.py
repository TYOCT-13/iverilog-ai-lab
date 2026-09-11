"""从真实开源 Verilog 项目**度量**编码与验证约定，产出可追溯的规约包。

## 这个模块解决什么问题

题目方向"（二）AI 开发工具与开源协作"把"知识库与检索""数据/知识工具"列为可聚焦的
工作。本项目此前的验证规则是**手写**的通用工程原则，只有一个概括性的来源说明；
这个模块把规则变成**从真实开源代码里量出来的、可追溯到具体提交与许可证的**知识资产。

## 三条不可让步的口径

1. **只度量，不复制。** 扫描上游源码的统计特征，输出的是**聚合比例与出处**，
   不搬运上游任何一行代码。因此不产生衍生作品，也不触发再分发义务。
2. **区分"事实"与"建议"。** 每个探针记录的是"上游 N 个文件中有 M 个如此"这样的
   事实；据此生成的提示词会标注置信度（`strong` / `moderate` / `weak`），
   **覆盖率低的一律写成"上游较少见"而不是"禁止"**。
3. **不参与判决。** 生成的规约只作为 AI 规划的上下文，帮助模型写出更贴合社区习惯的
   测试计划；它对 PASS/FAIL 没有任何影响，也无法改变 testbench 的结构——testbench
   仍由确定性模板生成。

## 数据流

    upstream repo (pinned commit)
      → 度量聚合（本模块 measure）
      → data/opensource_conventions.json（含出处、许可证、每文件 sha256）
      → render_conventions_context()（给 AI 规划器的提示片段）
      → AI 生成 TestPlan → 校验 → 确定性 testbench → Icarus 裁决
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import re
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "ConventionSource",
    "ProbeResult",
    "PROBES",
    "DEFAULT_SOURCES",
    "strip_comments",
    "measure_source",
    "measure_file",
    "render_conventions_context",
    "load_conventions",
]

# ---------------------------------------------------------------------------
# 上游来源声明
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ConventionSource:
    """一个被度量的上游项目。``ref`` 必须是**固定提交**，否则不可复现。"""

    key: str
    repository: str
    ref: str
    spdx: str
    license_url: str
    note: str = ""

    @property
    def archive_url(self) -> str:
        return f"https://codeload.github.com/{self.repository}/tar.gz/{self.ref}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "ref": self.ref,
            "spdx": self.spdx,
            "license_url": self.license_url,
            "note": self.note,
        }


#: 默认度量的上游项目。
#:
#: 选型依据：都是被广泛使用的开源 Verilog 代码库（非教学玩具），许可证明确，
#: 且覆盖"接口 / 握手 / 流水线"这一本项目最关心的设计类型。
#:
#: ``ref`` 固定为**提交哈希**而不是分支名——分支会移动，度量结果就不可复现。
#: 这些哈希由 `scripts/ingest_open_source_conventions.py --refresh-refs` 从
#: 上游 API 读取并写回，不是手写的。
DEFAULT_SOURCES: tuple[ConventionSource, ...] = (
    ConventionSource(
        key="verilog-axi",
        repository="alexforencich/verilog-axi",
        ref="516bd5dadc3365b7f9e225d2af8fe0b8d804fe53",
        spdx="MIT",
        license_url="https://github.com/alexforencich/verilog-axi/blob/master/LICENSE",
        note="AXI 接口、FIFO 与握手实现，工程化程度高",
    ),
    ConventionSource(
        key="wb2axip",
        repository="ZipCPU/wb2axip",
        ref="2e8d3bc2d26ddc33d1881022a2a2b9d3f0c16b9b",
        spdx="GPL-3.0-or-later",
        license_url="https://github.com/ZipCPU/wb2axip/blob/master/LICENSE",
        note="总线与握手参考实现；GPL 项目——本模块只读取统计量、不复制代码",
    ),
)


# ---------------------------------------------------------------------------
# 注释剥离（``timescale`` 必须保留，否则会误判"缺少 timescale"）
# ---------------------------------------------------------------------------
#: 复位类标识符的**词元**匹配：`rst` / `reset` 必须是独立词元（可带下划线前后缀）。
#: 不能用子串匹配——`burst` 里就含 "rst"。
_RESET_TOKEN = re.compile(r"(?:^|_)(?:rst|reset)(?:_|$)", re.I)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")
_STRING = re.compile(r'"(?:\\.|[^"\\])*"')


def strip_comments(source: str) -> str:
    """去掉注释与字符串字面量，但保留 ``timescale`` 指令。

    不剥注释会让 ``// use <= here`` 之类的说明文字被当成代码证据；不保留
    ``timescale`` 则会产生"每个文件都缺 timescale"这种全量误报（静态规则那边
    踩过同一个坑）。字符串字面量里的内容同样不是代码，一并替换为占位符。
    """

    kept: list[str] = []

    def _keep_directive(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return f"\x00{len(kept) - 1}\x00"

    guarded = re.sub(r"`timescale[^\n]*", _keep_directive, source)
    guarded = _BLOCK_COMMENT.sub(" ", guarded)
    guarded = _LINE_COMMENT.sub(" ", guarded)
    guarded = _STRING.sub('""', guarded)
    for index, directive in enumerate(kept):
        guarded = guarded.replace(f"\x00{index}\x00", directive)
    return guarded


# ---------------------------------------------------------------------------
# 探针：每个探针给出一句"事实"，而不是一条"规则"
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProbeResult:
    probe: str
    title: str
    numerator: int
    denominator: int
    unit: str
    #: 覆盖率达到该比例即可作为较强建议
    strong_threshold: float = 0.9
    moderate_threshold: float = 0.6

    @property
    def ratio(self) -> float:
        return self.numerator / self.denominator if self.denominator else 0.0

    @property
    def confidence(self) -> str:
        if not self.denominator:
            return "unknown"
        if self.ratio >= self.strong_threshold:
            return "strong"
        if self.ratio >= self.moderate_threshold:
            return "moderate"
        return "weak"

    def statement(self) -> str:
        """把统计事实渲染成一句话，措辞随置信度变化。"""

        percent = f"{self.ratio * 100:.0f}%"
        if self.confidence == "strong":
            lead = f"上游普遍如此（{self.numerator}/{self.denominator}，{percent}）"
        elif self.confidence == "moderate":
            lead = f"上游多数如此（{self.numerator}/{self.denominator}，{percent}）"
        else:
            lead = f"上游较少如此（{self.numerator}/{self.denominator}，{percent}），不构成约定"
        return f"{self.title}：{lead}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe": self.probe,
            "title": self.title,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unit": self.unit,
            "ratio": round(self.ratio, 4),
            "confidence": self.confidence,
        }


#: 探针注册表：``probe_id -> (标题, 匹配函数)``。
#: 匹配函数接收**已剥离注释**的源码，返回 (分子, 分母)。
def _probe_timescale(source: str) -> tuple[int, int]:
    return (1 if re.search(r"`timescale", source) else 0, 1)


def _probe_nonblocking_in_clocked(source: str) -> tuple[int, int]:
    """时序块里**出现**非阻塞赋值 ``<=``。

    注意这个探针的口径偏宽松：它只看块内是否出现过 ``<=``，因此对"时序块里同时
    写寄存器和组合中间量"的风格会给出偏低的值（wb2axip 实测 58%）。真正有说服力
    的约定是下面那一条——**时序块里没有阻塞赋值**。保留本探针是为了让读者看到
    宽严两种口径的差异，而不是把它当成硬指标。
    """

    blocks = _clocked_always_bodies(source)
    if not blocks:
        return (0, 0)
    using = sum(1 for body in blocks if "<=" in body)
    return (using, len(blocks))


def _probe_blocking_absent_in_clocked(source: str) -> tuple[int, int]:
    """时序块里**没有**阻塞赋值（排除 ``for`` 循环变量这类合法用法）。"""

    blocks = _clocked_always_bodies(source)
    if not blocks:
        return (0, 0)
    clean = 0
    for body in blocks:
        assignments = re.findall(r"^\s*([A-Za-z_]\w*)\s*=(?!=)", body, re.M)
        # for 循环的循环变量赋值是合法的阻塞用法
        loop_vars = set(re.findall(r"\bfor\s*\(\s*([A-Za-z_]\w*)\s*=", body))
        if not [name for name in assignments if name not in loop_vars]:
            clean += 1
    return (clean, len(blocks))


def _probe_ansi_ports(source: str) -> tuple[int, int]:
    """模块头是否为 ANSI 风格（端口方向写在端口列表里）。

    正则必须先吃掉参数列表再吃端口列表。实测的常见写法有三种，都要覆盖：

        module foo (input a, output b);            # 参数与端口同行
        module foo #(parameter W = 8) (input a);   # 参数在同一行
        module foo #                               # 参数与端口都换行
        (
            parameter W = 8
        )
        (
            input a
        );

    早期版本只覆盖前两种（且参数列表用 ``[^)]*`` 遇到 ``#`` 换行就失配），
    在 83 个文件中只匹配到 4 个模块头，进而把"ANSI 端口 4/4 = 100%"写进产物——
    数字看着漂亮，实际是正则失效。
    """

    modules = re.findall(
        r"\bmodule\s+\w+\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;",
        source,
        re.S,
    )
    if not modules:
        return (0, 0)
    ansi = sum(1 for header in modules if re.search(r"\b(input|output|inout)\b", header))
    return (ansi, len(modules))


def _probe_default_in_case(source: str) -> tuple[int, int]:
    cases = re.findall(r"\bcase[xz]?\s*\(.*?\bendcase", source, re.S)
    if not cases:
        return (0, 0)
    with_default = sum(1 for block in cases if re.search(r"\bdefault\b", block))
    return (with_default, len(cases))


def _probe_localparam_for_states(source: str) -> tuple[int, int]:
    has_param = bool(re.search(r"\b(localparam|parameter)\b", source))
    return (1 if has_param else 0, 1)


def _probe_active_low_reset_naming(source: str) -> tuple[int, int]:
    """低有效复位是否命名为 ``xxx_n``。

    必须按**词元**匹配 ``rst`` / ``reset``，不能用 ``\\w*(?:rst|reset)\\w*``：
    后者会把 ``burst``（含 "rst" 子串）当成复位名。实测该 bug 让 verilog-axi 的
    "复位名"从 35 个虚增到 491 个，得出的比例毫无意义。
    """

    tokens = re.findall(r"\b\w+\b", source)
    names = {name for name in tokens if _RESET_TOKEN.search(name)}
    if not names:
        return (0, 0)
    suffix_n = sum(1 for name in names if name.lower().endswith("_n"))
    return (suffix_n, len(names))


def _probe_async_reset(source: str) -> tuple[int, int]:
    sens = re.findall(r"always\s*@\s*\(([^)]*)\)", source, re.S)
    clocked = [item for item in sens if re.search(r"posedge|negedge", item, re.I)]
    if not clocked:
        return (0, 0)
    async_reset = sum(
        1 for item in clocked if len(re.findall(r"posedge|negedge", item, re.I)) >= 2
    )
    return (async_reset, len(clocked))


def _probe_clocked_always(source: str) -> tuple[int, int]:
    sens = re.findall(r"always\s*@\s*\(([^)]*)\)", source, re.S)
    if not sens:
        return (0, 0)
    clocked = sum(1 for item in sens if re.search(r"posedge|negedge", item, re.I))
    return (clocked, len(sens))


def _probe_declared_width_on_ports(source: str) -> tuple[int, int]:
    """端口声明的位宽显式程度：``[7:0]`` vs 只写 ``input wire a``。"""

    ports = re.findall(
        r"\b(input|output|inout)\b\s+(?:wire|reg|logic)?\s*(\[[^\]]+\])?\s*([A-Za-z_]\w*)",
        source,
    )
    if not ports:
        return (0, 0)
    # 只统计看起来是向量的名字（含 bus 语义提示）或显式带位宽的声明
    explicit = sum(1 for _direction, width, _name in ports if width)
    return (explicit, len(ports))


def _clocked_always_bodies(source: str) -> list[str]:
    """取出时序 ``always`` 块的**块体**，用于统计赋值风格。

    用花括号/``begin``-``end`` 配平来切块，而不是靠正则贪婪匹配——后者在嵌套
    ``begin`` 上会切错，进而把组合块的阻塞赋值算进时序块，得出错误的结论。
    """

    bodies: list[str] = []
    for match in re.finditer(r"always\s*@\s*\(([^)]*)\)", source, re.S):
        if not re.search(r"posedge|negedge", match.group(1), re.I):
            continue
        start = match.end()
        rest = source[start:]
        begin_index = rest.find("begin")
        if begin_index < 0:
            # 单语句块：取到下一个分号
            end = rest.find(";")
            bodies.append(rest[: end + 1] if end >= 0 else rest)
            continue
        depth = 0
        cursor = begin_index
        while cursor < len(rest):
            if rest.startswith("begin", cursor):
                depth += 1
                cursor += 5
            elif rest.startswith("end", cursor):
                depth -= 1
                cursor += 3
                if depth == 0:
                    bodies.append(rest[begin_index:cursor])
                    break
            else:
                cursor += 1
        else:
            bodies.append(rest[begin_index:])
    return bodies


PROBES: tuple[tuple[str, str, Any], ...] = (
    ("timescale", "文件声明了 `timescale", _probe_timescale),
    ("ansi_ports", "模块使用 ANSI 风格端口列表", _probe_ansi_ports),
    ("clocked_always", "always 块以时钟边沿为敏感条件", _probe_clocked_always),
    ("nonblocking_in_clocked", "时序块内出现过非阻塞赋值 <=（宽口径）", _probe_nonblocking_in_clocked),
    ("no_blocking_in_clocked", "时序块没有阻塞赋值（for 循环变量除外）", _probe_blocking_absent_in_clocked),
    ("async_reset", "时序块敏感列表含复位边沿（异步复位）", _probe_async_reset),
    ("active_low_reset_naming", "低有效复位命名为 xxx_n", _probe_active_low_reset_naming),
    ("default_in_case", "case 语句带 default 分支", _probe_default_in_case),
    ("param_for_states", "使用参数/localparam 表示状态或常量", _probe_localparam_for_states),
    ("explicit_port_width", "端口声明显式写出位宽", _probe_declared_width_on_ports),
)


# ---------------------------------------------------------------------------
# 度量
# ---------------------------------------------------------------------------
def measure_file(path: Path) -> dict[str, ProbeResult]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_comments(raw)
    results: dict[str, ProbeResult] = {}
    for probe_id, title, fn in PROBES:
        numerator, denominator = fn(cleaned)
        results[probe_id] = ProbeResult(probe_id, title, int(numerator), int(denominator), "file")
    return results


def measure_source(root: Path, *, globs: Sequence[str] = ("*.v", "*.sv")) -> dict[str, Any]:
    """度量一个已解包的源码树，返回聚合结果与每文件指纹。"""

    files = sorted(
        path
        for pattern in globs
        for path in root.rglob(pattern)
        if path.is_file()
    )
    totals: dict[str, list[int]] = {probe_id: [0, 0] for probe_id, _, _ in PROBES}
    digests: list[dict[str, str]] = []
    for path in files:
        raw = path.read_bytes()
        digests.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        )
        for probe_id, result in measure_file(path).items():
            totals[probe_id][0] += result.numerator
            totals[probe_id][1] += result.denominator

    probes = []
    for probe_id, title, _fn in PROBES:
        numerator, denominator = totals[probe_id]
        probes.append(ProbeResult(probe_id, title, numerator, denominator, "file"))
    return {
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in digests),
        "files": digests,
        "probes": [item.to_dict() for item in probes],
    }


# ---------------------------------------------------------------------------
# 拉取上游（固定提交）
# ---------------------------------------------------------------------------
def fetch_source(source: ConventionSource, cache_dir: Path) -> Path:
    """下载并解包固定提交的源码树到 ``cache_dir``，返回解包后的根目录。

    只做一次；已存在则直接复用（目录名含提交号，因此不会串味）。
    """

    target = cache_dir / f"{source.key}-{source.ref[:12]}"
    if target.is_dir() and any(target.iterdir()):
        return target
    target.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        source.archive_url,
        headers={"User-Agent": "iverilog-ai-lab-conventions/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        # 顶层是 <repo>-<ref>/；剥掉一层，方便按相对路径记录指纹
        members = archive.getmembers()
        prefix = members[0].name.split("/")[0] + "/" if members else ""
        for member in members:
            if not member.name.startswith(prefix) or member.name == prefix:
                continue
            member.name = member.name[len(prefix):]
            archive.extract(member, target, filter="data")
    return target


# ---------------------------------------------------------------------------
# 渲染：给 AI 规划器的提示片段
# ---------------------------------------------------------------------------
def render_conventions_context(
    conventions: Mapping[str, Any],
    *,
    min_confidence: str = "moderate",
    max_items: int = 8,
) -> str:
    """把规约包渲染成一段**只陈述事实**的提示片段。

    措辞规则：覆盖率不足的探针会被写成"上游较少如此，不构成约定"，
    避免模型把个案当成规范。
    """

    order = {"strong": 0, "moderate": 1, "weak": 2, "unknown": 3}
    limit = order.get(min_confidence, 1)
    lines = [
        "以下约定来自对开源 Verilog 项目的实测统计（非本项目自定规则）。",
        "它们用于让你的测试计划更贴合社区惯例；它们**不改变判定口径**，"
        "也不能作为期望值的依据。",
    ]
    sources = conventions.get("sources", [])
    for source in sources:
        lines.append(
            f"- 来源：{source.get('repository')} @ {str(source.get('ref'))[:12]}"
            f"（{source.get('spdx')}），共度量 {source.get('file_count')} 个 Verilog 文件"
        )
    lines.append("测得约定：")
    emitted = 0
    for source in sources:
        for probe in source.get("probes", []):
            if order.get(str(probe.get("confidence")), 3) > limit:
                continue
            if emitted >= max_items:
                break
            percent = probe.get("ratio", 0) * 100
            lines.append(
                f"- {probe.get('title')}：{probe.get('numerator')}/{probe.get('denominator')}"
                f"（{percent:.0f}%）"
            )
            emitted += 1
    if emitted == 0:
        lines.append("- （没有达到置信度阈值的约定）")
    return "\n".join(lines)


def load_conventions(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "1.0", "sources": []}
    return json.loads(path.read_text(encoding="utf-8"))
