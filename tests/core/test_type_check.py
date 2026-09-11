"""类型检查门禁：`src` / `ui` / `scripts` 必须保持 0 error。

先例（都是这套检查抓出来的真问题，不是风格洁癖）：

1. `core/static_review.py` 里 `_numeric_findings` 被定义了两次——后一份静默覆盖
   前一份，前一份成了永远不执行的死代码；
2. `ui/app.py` 里 `rules_manifest`（正确名字是 `rule_manifest`）与"先用后定义"的
   `_contract()`：都是 `NameError`，而线性脚本里一抛就把整页渲染中断；
3. 若干"把 None 当字符串用"的链路（`getenv(...).strip()`、`None.value`）。

配置写在 `pyproject.toml` 的 `[tool.mypy]`，因此命令行与 CI 用的是同一套参数。
未安装 mypy 时跳过（本地环境可选），CI 会安装。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mypy") is None, reason="未安装 mypy（CI 会安装）"
)


def test_type_check_is_clean():
    completed = subprocess.run(
        [sys.executable, "-m", "mypy"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-2000:]
    assert "Success" in completed.stdout, completed.stdout[-2000:]
