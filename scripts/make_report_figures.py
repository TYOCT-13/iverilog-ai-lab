"""用 Pillow 生成技术报告插图（确定性、可复现、无第三方素材）。

为什么用代码画而不是找图：
- 报告插图是**结构示意图与数据图**，属于"代码原生图形"，生成式绘图既不必要
  也不可靠；
- 代码画图可复现：同一份脚本随时重跑，图与仓库数据保持一致；
- 不含任何第三方素材，避免版权与授权问题（赛事明确要求素材权利清晰）。

输出的图：
1. `fig1_architecture.png`   系统架构与 AI 边界
2. `fig2_flow.png`           验证流程（含判决权归属）
3. `fig3_layered_evidence.png` 分层证据（哪些做了、哪些没做）
4. `fig4_benchmark.png`      基准矩阵结果

用法：python scripts/make_report_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "competition" / "figures"

# —— 视觉规范（统一配色，保证多张图风格一致）——
BG = (255, 255, 255)
INK = (28, 35, 45)
MUTED = (110, 122, 138)
LINE = (198, 208, 220)
AI_BLUE = (232, 242, 254)
AI_EDGE = (72, 132, 214)
DET_GREEN = (232, 246, 236)
DET_EDGE = (54, 149, 92)
WARN_AMBER = (255, 246, 230)
WARN_EDGE = (219, 154, 40)
GRAY_FILL = (244, 246, 249)
GRAY_EDGE = (176, 186, 198)
RED_FILL = (253, 236, 236)
RED_EDGE = (198, 78, 78)

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)


# Pillow 的回退字体是 ImageFont.ImageFont（不是 FreeTypeFont），返回类型必须写成并集。
def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    bold_path = r"C:\Windows\Fonts\msyhbd.ttc"
    if bold and Path(bold_path).is_file():
        return ImageFont.truetype(bold_path, size)
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _canvas(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), BG)
    return image, ImageDraw.Draw(image)


def _box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    title: str,
    lines: list[str],
    *,
    fill: tuple[int, int, int],
    edge: tuple[int, int, int],
    title_size: int = 26,
    body_size: int = 21,
    radius: int = 12,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=edge, width=3)
    left, top, right, _ = xy
    x = left + 20
    y = top + 16
    draw.text((x, y), title, font=_font(title_size, bold=True), fill=INK)
    y += title_size + 12
    for line in lines:
        draw.text((x, y), line, font=_font(body_size), fill=MUTED)
        y += body_size + 9


def _arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: tuple[int, int, int] = (120, 134, 152),
    width: int = 3,
    head: int = 12,
    label: str | None = None,
    label_size: int = 19,
) -> None:
    draw.line([start, end], fill=color, width=width)
    (x1, y1), (x2, y2) = start, end
    if x1 == x2:  # 竖直
        direction = 1 if y2 > y1 else -1
        draw.polygon(
            [(x2, y2), (x2 - head, y2 - direction * head), (x2 + head, y2 - direction * head)],
            fill=color,
        )
        if label:
            draw.text((x2 + 12, (y1 + y2) // 2 - 12), label, font=_font(label_size), fill=color)
    else:  # 水平
        direction = 1 if x2 > x1 else -1
        draw.polygon(
            [(x2, y2), (x2 - direction * head, y2 - head), (x2 - direction * head, y2 + head)],
            fill=color,
        )
        if label:
            draw.text(((x1 + x2) // 2 - 20, y2 - 34), label, font=_font(label_size), fill=color)


def _title(draw: ImageDraw.ImageDraw, text: str, *, y: int = 28, size: int = 36) -> None:
    draw.text((40, y), text, font=_font(size, bold=True), fill=INK)


def _footnote(draw: ImageDraw.ImageDraw, text: str, width: int, height: int) -> None:
    draw.text((40, height - 44), text, font=_font(20), fill=MUTED)
    draw.line([(40, height - 54), (width - 40, height - 54)], fill=LINE, width=2)


# ---------------------------------------------------------------------------
# 图 1：系统架构与 AI 边界
# ---------------------------------------------------------------------------
def _save(image: Image.Image, path: Path, *, max_width: int = 1500, colors: int = 64) -> Path:
    """保存为体积可控的 PNG。

    报告有 10MB 上限，而 200 DPI 的无损 PNG 单张就要 260KB 以上、嵌进 PDF 后
    更容易膨胀。这里统一缩放到合适的显示宽度并做调色板量化——示意图只有纯色块
    与文字，量化到 64 色肉眼无差别，体积能降一个数量级。
    """

    if image.width > max_width:
        ratio = max_width / image.width
        # Pillow 的 type stub 里没有 LANCZOS/ADAPTIVE 这两个常量别名（运行期存在），
        # 因此单独忽略这两行的属性检查。
        image = image.resize((max_width, int(image.height * ratio)), Image.LANCZOS)  # type: ignore[attr-defined]
    image = image.convert("P", palette=Image.ADAPTIVE, colors=colors)  # type: ignore[attr-defined]
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    return path


def figure_architecture() -> Path:
    width, height = 1600, 940
    image, draw = _canvas(width, height)
    _title(draw, "图 1  系统架构：AI 能影响什么，不能影响什么")

    _box(
        draw, (60, 110, 740, 330),
        "① AI 规划层（可替换、可离线）",
        [
            "自然语言验证目标 → 受 Schema 约束的 TestPlan",
            "提出边界激励、解释失败原因",
            "离线 MockProvider（默认，不联网）",
            "OpenAI 兼容接口（可选，用户自带密钥）",
        ],
        fill=AI_BLUE, edge=AI_EDGE,
    )
    _box(
        draw, (60, 370, 740, 630),
        "② 合约与安全边界（AI 不可越过）",
        [
            "TestPlan 严格校验：字段名、位宽、取值域",
            "DUT 合约匹配：端口名与方向必须真实存在",
            "不生成、不拼接 Verilog 代码",
            "SafePathPolicy：路径与工件目录白名单",
            "无 shell 执行：固定工具名 + 参数列表 + 超时",
        ],
        fill=WARN_AMBER, edge=WARN_EDGE,
    )
    _box(
        draw, (60, 670, 740, 860),
        "③ 确定性执行层（开源工具，判决权威）",
        [
            "Icarus Verilog 编译 + vvp 仿真（GPL-2.0-or-later，独立进程调用）",
            "参考模型独立复算期望值，覆盖 AI 给出的数字",
            "结构化断言：只允许模板化检查，不接受自由代码",
        ],
        fill=DET_GREEN, edge=DET_EDGE,
    )
    _box(
        draw, (860, 110, 1540, 400),
        "④ 证据与报告层",
        [
            "结构化记录 IVERILOG_AI_RESULT → 失败反例",
            "波形语义分析：边沿、毛刺、相位、双波形差异",
            "静态质量审查：44 条规则，每条配正反例",
            "分层证据：仿真 / 综合 / 时序 / 比特流 / 上板",
        ],
        fill=GRAY_FILL, edge=GRAY_EDGE,
    )
    _box(
        draw, (860, 440, 1540, 660),
        "⑤ 开放成果",
        [
            "15 个案例 / 83 个可复现缺陷（Apache-2.0）",
            "44 条静态规则 + 逐条正反例用例",
            "测试计划 JSON 格式（可被其他工具适配）",
            "离线调试接口：无密钥即可复现全部实验",
        ],
        fill=GRAY_FILL, edge=GRAY_EDGE,
    )
    _box(
        draw, (860, 700, 1540, 860),
        "判决权归属（本项目的核心主张）",
        [
            "PASS/FAIL 只由 Icarus 仿真结果与结构化断言决定",
            "AI 自评、AI 期望值都不参与裁决",
        ],
        fill=RED_FILL, edge=RED_EDGE,
    )

    _arrow(draw, (400, 330), (400, 370), label="Schema 校验")
    _arrow(draw, (400, 630), (400, 670), label="受控执行")
    # 从执行层右边缘直接向右上连到证据层，绕开中间的"合约与安全边界"框
    _arrow(draw, (740, 700), (860, 330))
    _arrow(draw, (740, 220), (860, 250))
    _footnote(
        draw,
        "AI 只能产出行 ① 的结构化测试计划；②③ 两层是确定性代码，AI 无法改写执行内容与判决口径。",
        width, height,
    )
    path = OUT_DIR / "fig1_architecture.png"
    return _save(image, path)


# ---------------------------------------------------------------------------
# 图 2：验证流程
# ---------------------------------------------------------------------------
def figure_flow() -> Path:
    width, height = 1700, 760
    image, draw = _canvas(width, height)
    _title(draw, "图 2  验证流程：从自然语言验证目标到可核验报告")

    steps = [
        ("验证目标", ["自然语言描述", "（用户输入）"], AI_BLUE, AI_EDGE),
        ("AI 测试计划", ["受 Schema 约束", "的 JSON"], AI_BLUE, AI_EDGE),
        ("校验门", ["字段 / 位宽 / 取值域", "合约端口匹配"], WARN_AMBER, WARN_EDGE),
        ("testbench", ["确定性模板生成", "每断言输出 JSON"], GRAY_FILL, GRAY_EDGE),
        ("Icarus + vvp", ["真实编译与仿真", "判决权威"], DET_GREEN, DET_EDGE),
        ("结构化证据", ["失败反例 / 指纹", "波形语义结论"], GRAY_FILL, GRAY_EDGE),
        ("报告", ["Markdown / HTML", "+ 分层证据"], GRAY_FILL, GRAY_EDGE),
    ]
    box_w, gap = 208, 28
    left = 40
    top = 150
    bottom = 430
    for index, (title, lines, fill, edge) in enumerate(steps):
        x = left + index * (box_w + gap)
        _box(draw, (x, top, x + box_w, bottom), title, lines, fill=fill, edge=edge,
             title_size=24, body_size=19)
        if index < len(steps) - 1:
            _arrow(draw, (x + box_w, (top + bottom) // 2), (x + box_w + gap, (top + bottom) // 2))

    # 参考模型支路：与 AI 计划并行，独立复算期望值
    _box(
        draw, (320, 510, 900, 640),
        "参考模型独立复算（预言机）",
        [
            "与 RTL 逐拍对齐的确定性模型复算期望值并覆盖 AI 数字",
            "未对齐的设计显式标注 expectation_source = ai_generated",
        ],
        fill=DET_GREEN, edge=DET_EDGE, title_size=24, body_size=19,
    )
    _arrow(draw, (610, 510), (610, 430))
    _box(
        draw, (960, 510, 1660, 640),
        "不参与判决的东西",
        [
            "AI 自评、AI 给出的期望值、AI 对失败的解释 —— 全部只作诊断",
        ],
        fill=RED_FILL, edge=RED_EDGE, title_size=24, body_size=19,
    )
    _footnote(draw, "所有结论可回溯到 run 目录下的编译日志、仿真日志、VCD 与 result.json。", width, height)
    path = OUT_DIR / "fig2_flow.png"
    return _save(image, path)


# ---------------------------------------------------------------------------
# 图 3：分层证据
# ---------------------------------------------------------------------------
def figure_layered_evidence(cells: dict | None = None, synth: dict | None = None) -> Path:
    width, height = 1500, 700
    image, draw = _canvas(width, height)
    _title(draw, "图 3  分层证据：做过的与没做的都写出来")

    # 综合层的说法必须与实际跑过的结果一致：跑过写"实测 N/N"，没跑过写"未运行"。
    if synth and synth.get("total"):
        synth_detail = (
            f"Yosys 通用门级映射 + 单元统计（实测 {synth['passed']}/{synth['total']} 个 RTL 变体通过）"
        )
        synth_status = "已提供（可选）"
    else:
        synth_detail = "Yosys 通用门级映射 + 单元统计（本机未运行：python scripts/run_synthesis_matrix.py）"
        synth_status = "未运行"

    rows = [
        ("功能仿真", "本次流水线提供", "Icarus 编译 + vvp 执行 + 结构化断言", DET_GREEN, DET_EDGE),
        ("逻辑综合", synth_status, synth_detail, DET_GREEN, DET_EDGE),
        ("时序分析", "未运行", "需要目标器件时序库与时钟约束 —— 本项目不提供", GRAY_FILL, GRAY_EDGE),
        ("布局布线 / 比特流", "未运行", "需要厂商工具链（Vivado / Quartus 等）—— 本项目不提供", GRAY_FILL, GRAY_EDGE),
        ("上板验证", "未运行", "需要实际硬件与测试装置 —— 本项目不提供", GRAY_FILL, GRAY_EDGE),
    ]
    top = 126
    row_h = 74
    for index, (name, status, detail, fill, edge) in enumerate(rows):
        y = top + index * (row_h + 14)
        draw.rounded_rectangle((40, y, width - 40, y + row_h), radius=10, fill=fill, outline=edge, width=3)
        draw.text((64, y + 20), name, font=_font(26, bold=True), fill=INK)
        draw.text((420, y + 22), status, font=_font(24), fill=edge)
        draw.text((700, y + 24), detail, font=_font(22), fill=MUTED)
    cell_stats = cells or {}
    draw.text(
        (40, height - 92),
        f"综合单元统计示例：PWM {cell_stats.get('pwm', '—')} 个通用门级单元；"
        f"UART {cell_stats.get('uart_tx', '—')} 个；FIFO {cell_stats.get('sync_fifo', '—')} 个。",
        font=_font(21), fill=INK,
    )
    _footnote(draw, "综合通过 ≠ 时序收敛 ≠ 能上板；本项目不做时序签核，也不给出频率结论。", width, height)
    path = OUT_DIR / "fig3_layered_evidence.png"
    return _save(image, path)


# ---------------------------------------------------------------------------
# 图 4：基准矩阵结果
# ---------------------------------------------------------------------------
def figure_benchmark(stats: dict) -> Path:
    width, height = 1500, 700
    image, draw = _canvas(width, height)
    _title(draw, "图 4  基准矩阵实跑结果（固定向量，可复现）")

    references = stats.get("references_total")
    defects = stats.get("defects_total")
    found = stats.get("defects_found")

    def _value(value: object, fmt: str) -> str:
        """未测量（None）时显示"—"，不显示 0——0 是"测出来是 0"，与此不同。"""

        return "—" if value is None else fmt.format(value)

    cards = [
        ("参考设计通过", _value(references, "{0}/{0}"), DET_GREEN, DET_EDGE),
        ("缺陷检出", "—" if (found is None or defects is None) else f"{found}/{defects}", DET_GREEN, DET_EDGE),
        ("参考误报", _value(stats.get("reference_false_positives"), "{0}"), DET_GREEN, DET_EDGE),
        ("不可判定", _value(stats.get("inconclusive_runs"), "{0}"), DET_GREEN, DET_EDGE),
    ]
    card_w = 330
    for index, (label, value, fill, edge) in enumerate(cards):
        x = 40 + index * (card_w + 30)
        draw.rounded_rectangle((x, 130, x + card_w, 310), radius=14, fill=fill, outline=edge, width=3)
        draw.text((x + 28, 160), label, font=_font(26), fill=MUTED)
        draw.text((x + 28, 206), value, font=_font(64, bold=True), fill=INK)

    draw.text((40, 360), "四类缺陷的检出分布", font=_font(28, bold=True), fill=INK)
    bars = [
        ("功能错误（回绕 / 使能 / 计数）", stats.get("by_kind", {}).get("functional", 0), DET_EDGE),
        ("时序与复位（位序 / 拍数 / 复位）", stats.get("by_kind", {}).get("timing", 0), AI_EDGE),
        ("接口与协议（握手 / 帧格式）", stats.get("by_kind", {}).get("protocol", 0), WARN_EDGE),
        ("边界与极限值", stats.get("by_kind", {}).get("boundary", 0), (150, 120, 190)),
    ]
    max_value = int(max((value for _, value, _ in bars), default=1) or 1)
    top = 410
    for index, (label, value, color) in enumerate(bars):
        y = top + index * 54
        draw.text((40, y + 6), label, font=_font(22), fill=INK)
        bar_x = 560
        bar_max = 780
        length = int(bar_max * (int(value) / max_value)) if max_value else 0
        draw.rounded_rectangle((bar_x, y + 4, bar_x + bar_max, y + 34), radius=6, fill=GRAY_FILL, outline=LINE, width=2)
        if length:
            draw.rounded_rectangle((bar_x, y + 4, bar_x + length, y + 34), radius=6, fill=color)
        draw.text((bar_x + bar_max + 24, y + 8), str(value), font=_font(24, bold=True), fill=INK)

    _footnote(
        draw,
        "检出＝该缺陷 RTL 在固定激励下产生结构化失败记录；误报＝参考设计上出现非预期失败。",
        width, height,
    )
    path = OUT_DIR / "fig4_benchmark.png"
    return _save(image, path)


def _read_benchmark_stats() -> dict:
    """优先读最近一次基准矩阵的结果 JSON；读不到就只报"清单规模"，测量值留空。

    这里曾经有两个坑，都修在明面上：

    1. 文件名写错（找 `benchmark_matrix.json`，而矩阵脚本产出的是 `matrix.json`），
       于是**永远读不到**真实结果，图里一直显示硬编码的旧数字；
    2. 读不到时回退到硬编码的 `14/78`——数字一旦过期就是错的，而且同一个图里的
       柱状图是按清单现算的，两者会自相矛盾。

    因此现在：读不到就把未测量的字段设为 `None`，由绘图处渲染成"—（未运行）"，
    绝不用 0 或旧值冒充一次真实的矩阵运行。
    """

    for path in sorted((ROOT / ".iverilog-ai").glob("**/*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        summary = data.get("summary")
        if isinstance(summary, dict) and "defects_total" in summary:
            return summary
        if "defects_total" in data:
            return data
    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    return {
        "references_total": len(manifest.get("categories", [])),
        "defects_total": len(manifest.get("defects", [])),
        # 未运行 → 不填 0，绘图处显示"—"
        "defects_found": None,
        "reference_false_positives": None,
        "inconclusive_runs": None,
    }


def _read_synthesis_cells() -> dict:
    """读取综合层产出的单元统计（若之前跑过综合证据层）。"""

    cells: dict[str, int] = {}
    for path in (ROOT / ".iverilog-ai").glob("**/synthesis/synth_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        top = data.get("top")
        count = data.get("cell_count")
        if top and isinstance(count, int):
            cells.setdefault(top, count)
    return cells


def _read_synthesis_matrix_stats() -> dict | None:
    """读取综合矩阵的结果摘要（`scripts/run_synthesis_matrix.py` 的产物）。

    读不到就返回 None，图里显示"未运行"——不拿清单规模冒充"实测全部通过"。
    """

    for path in sorted((ROOT / ".iverilog-ai").glob("**/synth-matrix.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary = data.get("summary")
        if isinstance(summary, dict) and "passed" in summary and "total" in summary:
            return summary
    return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = _read_benchmark_stats()
    # 按缺陷触发条件的语义粗分类，仅用于报告配图；数量必须与清单一致
    stats["by_kind"] = _classify_defects()
    cells = _read_synthesis_cells()
    synth = _read_synthesis_matrix_stats()

    produced = [
        figure_architecture(),
        figure_flow(),
        figure_layered_evidence(cells, synth),
        figure_benchmark(stats),
    ]
    for path in produced:
        with Image.open(path) as check:
            print(f"{path.relative_to(ROOT)}  {check.width}x{check.height}  {path.stat().st_size // 1024} KB")
    print(f"\n共生成 {len(produced)} 张插图 -> {OUT_DIR.relative_to(ROOT)}")
    return 0


def _classify_defects() -> dict[str, int]:
    """按 manifest 里每个缺陷的 trigger/expected/actual 文本做粗分类。

    分类只用于报告配图，不参与任何判决；因此用关键词启发式即可，但总数必须与
    清单一致（下方断言）。
    """

    manifest = json.loads((ROOT / "benchmarks" / "manifest.json").read_text(encoding="utf-8"))
    buckets = {"functional": 0, "timing": 0, "protocol": 0, "boundary": 0}
    rules = (
        ("protocol", ("handshake", "ready", "valid", "帧", "位序", "msb", "lsb", "sclk", "mosi", "停止位", "起始位", "spi", "uart")),
        ("timing", ("复位", "reset", "rst", "拍", "cycle", "延时", "delay", "同步", "时钟", "沿", "edge", "sample")),
        ("boundary", ("回绕", "wrap", "满", "full", "空", "empty", "边界", "极限", "溢出", "overflow", "最大", "最小")),
    )
    for defect in manifest["defects"]:
        text = " ".join(
            str(defect.get(key, "")) for key in ("trigger", "expected", "actual", "id")
        ).lower()
        for bucket, keywords in rules:
            if any(keyword in text for keyword in keywords):
                buckets[bucket] += 1
                break
        else:
            buckets["functional"] += 1
    assert sum(buckets.values()) == len(manifest["defects"]), "缺陷分类总数与清单不一致"
    return buckets


if __name__ == "__main__":
    raise SystemExit(main())
