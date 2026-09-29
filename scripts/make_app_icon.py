"""生成应用图标 `assets/iverilog-ai.ico`（离线、确定性、可重跑）。

为什么要自己画而不是借系统图标：桌面快捷方式要有一个能一眼认出来的图标，而
"借 chrome.exe 的图标"会让这个工具看起来像浏览器快捷方式，"用 shell32.dll 第 N 号图标"
则每次都得去猜编号、也无法解释它为什么合适。自己画一个反而更省事，而且改配色不用求人。

图形刻意简单，因为 .ico 会被缩到 16×16 显示：
深青底 + 一条青色方波（数字信号）+ 一枚白色对勾（判决通过）。**不放文字**——16 像素下
任何文字都糊成一团。

配色取自网页主题（`ui/app.py` 的 `--rl-cyan` 等），这样图标与页面是同一套视觉。
"""
from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "iverilog-ai.ico"
PREVIEW = ROOT / "assets" / "iverilog-ai.png"

#: 与网页主题一致（ui/app.py 的 CSS 变量）。
INK = (13, 27, 36)
CYAN = (0, 163, 180)
CYAN_DARK = (0, 112, 123)
WHITE = (255, 255, 255)

SIZES = (256, 128, 64, 48, 32, 16)


def _lanczos() -> int:
    """缩放算法常量，兼容 Pillow 9.1 之前没有 `Image.Resampling` 的版本。

    不用 `Image.LANCZOS` 直写：新版本 Pillow 的类型标注只声明了
    `Image.Resampling.LANCZOS`，直写会让类型检查报 `attr-defined`（运行期其实还能用，
    于是错误只出现在检查里，最容易被忽略）。
    """

    resampling = getattr(Image, "Resampling", None)
    if resampling is not None:
        return int(resampling.LANCZOS)
    return int(getattr(Image, "LANCZOS"))


LANCZOS = _lanczos()


def _rounded_background(size: int) -> Image.Image:
    """深色圆角底。用 8 倍超采样再缩回来，边缘才不会有锯齿。"""

    scale = 8
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    radius = int(size * scale * 0.22)
    draw.rounded_rectangle(
        [(0, 0), (size * scale - 1, size * scale - 1)], radius=radius, fill=INK + (255,)
    )
    # 顶部一道青色渐变条，让图标在深色任务栏上也能立住
    draw.rounded_rectangle(
        [(0, 0), (size * scale - 1, int(size * scale * 0.30))],
        radius=radius,
        fill=CYAN_DARK + (255,),
    )
    draw.rectangle([(0, int(size * scale * 0.16)), (size * scale - 1, int(size * scale * 0.30))], fill=CYAN_DARK + (255,))
    return canvas.resize((size, size), LANCZOS)


def _draw_square_wave(draw: ImageDraw.ImageDraw, size: int, scale: int) -> None:
    """一条方波：数字信号最直白的图形，16px 下也看得清是"跳变"。"""

    left, right = size * scale * 0.14, size * scale * 0.86
    low, high = size * scale * 0.62, size * scale * 0.40
    width = max(1, int(size * scale * 0.055))
    step = (right - left) / 6
    points = [
        (left, low), (left + step, low), (left + step, high),
        (left + 3 * step, high), (left + 3 * step, low),
        (left + 5 * step, low), (left + 5 * step, high), (right, high),
    ]
    draw.line(points, fill=CYAN + (255,), width=width, joint="curve")


def _draw_check(draw: ImageDraw.ImageDraw, size: int, scale: int) -> None:
    """一枚对勾：与"判决通过"对应。放在右下角，不与方波抢位置。"""

    width = max(1, int(size * scale * 0.075))
    points = [
        (size * scale * 0.60, size * scale * 0.74),
        (size * scale * 0.68, size * scale * 0.82),
        (size * scale * 0.85, size * scale * 0.60),
    ]
    draw.line(points, fill=WHITE + (255,), width=width, joint="curve")


def build(size: int = 256) -> Image.Image:
    """画一张 size×size 的图标；内部用 8 倍超采样保证线条与圆角平滑。"""

    scale = 8
    image = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(size * scale * 0.22)
    draw.rounded_rectangle(
        [(0, 0), (size * scale - 1, size * scale - 1)], radius=radius, fill=INK + (255,)
    )
    draw.rounded_rectangle(
        [(0, 0), (size * scale - 1, int(size * scale * 0.28))],
        radius=radius, fill=CYAN_DARK + (255,),
    )
    draw.rectangle(
        [(0, int(size * scale * 0.14)), (size * scale - 1, int(size * scale * 0.28))],
        fill=CYAN_DARK + (255,),
    )
    _draw_square_wave(draw, size, scale)
    if size >= 32:  # 16px 下对勾会糊成一个白点，不如不画
        _draw_check(draw, size, scale)
    return image.resize((size, size), LANCZOS)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    base.alpha_composite(build(256))
    base.save(OUTPUT, format="ICO", sizes=[(item, item) for item in SIZES])
    base.save(PREVIEW, format="PNG")
    print(f"已生成 {OUTPUT.relative_to(ROOT)}（{OUTPUT.stat().st_size / 1024:.1f} KB，含 {len(SIZES)} 种尺寸）")
    print(f"已生成 {PREVIEW.relative_to(ROOT)}（预览用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
