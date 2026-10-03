# 10 分钟复核指南

面向：**不想信我们的话、想自己跑一遍的人**（评委、第三方复核者、想复用的开发者）。

原则：**只列能自己核对的命令与期望数字**。任何一条对不上，就是我们对不上，请直接按第 4 节
反馈；不需要先相信任何结论。

---

## 0. 前置（实测：建 venv 约 5 秒 + 装依赖约 30 秒）

```powershell
python -V                      # 需要 3.11 或更高
git clone <仓库地址> ; cd iverilog-ai-lab
python -m venv .venv ; .\.venv\Scripts\Activate.ps1

python -m pip install -e ".[dev]"      # 跑下面的复核命令需要它（pytest / mypy / PyMuPDF / Pillow）
# 只跑产品、不跑复核的话，`pip install -e .` 就够：核心依赖只有 pydantic
# 要启动网页再加 UI 依赖：`python -m pip install -e ".[ui]"`
# Icarus Verilog：Windows 用 https://bleyer.org/icarus/ ；Linux 用 apt install iverilog
python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
```

**期望**：三个工具 `iverilog` / `vvp` / `yosys` 都打印出路径（`yosys` 可选；没有它时综合层
会显示"工具不可用"，不影响任何判决）。

**实测数字（本文档作者在干净虚拟环境里跑出来的，2026-09-29）**：

| 步骤 | 实测 |
|---|---|
| 建虚拟环境 | 约 5 秒 |
| `pip install -e .`（只有 pydantic） | 约 17 秒 |
| `pip install -e ".[dev]"` | 约 29 秒 |
| `pip install -e ".[ui]"` | 约 53 秒（需要数百 MB 磁盘） |
| `streamlit run ui/app.py` 起到可访问 | **约 1 秒**（健康检查返回 `ok`，首页同时可取） |

> **磁盘**：上面的数字是"时间成本"，还有"空间成本"。`.[ui]` 的依赖树（streamlit → pandas /
> pyarrow / pydeck …）需要数百 MB，产物目录 `.iverilog-ai/` 还会随实验增长；
> 本文档作者就曾在磁盘只剩 0 GB 时看到 `pip` 报 `[Errno 28] No space left on device`。
> 跑矩阵前请确认有若干 GB 空闲。
>
> 全程**不需要** API 密钥（只有第 0 节装依赖需要联网）。下面每一条都在离线状态可跑完。

---

## 1. 结论能不能信：跑基准矩阵（约 3 分钟）

```powershell
python scripts/run_benchmark_matrix.py
Get-Content .iverilog-ai/benchmark-matrix/matrix.md -TotalCount 40
```

**期望数字**（四个都要对上）：

| 项 | 期望 |
|---|---:|
| 参考设计 | **15 / 15** |
| 缺陷变体检出 | **83 / 83** |
| 参考误报 | **0** |
| 不可判定 | **0** |

**怎么不信我们**：

- 打开 `matrix.json`，随便挑一个缺陷，看它是否同时给出**原始日志路径、检查项、第几拍、
  期望值、实际值**——只有结论没有证据的，就是我们在吹；
- 挑一个"参考设计"，看它的期望值证据等级是不是 `reference_model`（`ai_generated` 就说明
  那一轮没有权威预言机，可信度不同）；
- 把 `rtl/` 下任意一个 `_bug_` 文件删掉几行再跑一遍，你应该看到**检出数下降**——
  如果数字纹丝不动，说明矩阵没有真的在跑你的改动。

---

## 2. AI 到底做了什么、没做什么（约 2 分钟）

```powershell
# 终端 A（可选）：离线调试模型，只监听回环地址
python -m iverilog_ai.ai.debug_server

# 终端 B
python -m iverilog_ai plan-run `
  --plan examples/simple_alu_plan.json `
  --contract examples/simple_alu_contract.json `
  --rtl rtl/simple_alu.v --output-dir runs\repro

Get-Content (Get-ChildItem runs\repro\run-*\report.md | Select-Object -First 1) -TotalCount 14
```

**期望**：报告头部四行分别是

```
- 运行状态：运行完成（`passed`）
- 设计结果：符合预期（`passed`）
- 证据结论：…
- 比对情况：N/N 条比对一致
```

**要点**：`设计结果` 才是"这份设计对不对"；`运行状态` 只说工具跑完了没有。
三层用词刻意不重叠——看到"运行完成"就知道那是工具状态，不是设计结论。

---

## 3. 最能说明问题的一条：两份 RTL 的行为对比（约 2 分钟）

```powershell
# ① 拿一份文件跟它自己比 —— 应当一致
python -m iverilog_ai verify-diff `
  --baseline rtl/mod10_counter.v --candidate rtl/mod10_counter.v `
  --output-dir runs\vd-same
echo "exit=$LASTEXITCODE"      # 期望 0

# ② 拿它跟一个缺陷变体比 —— 应当不同，并列出差异
python -m iverilog_ai verify-diff `
  --baseline rtl/mod10_counter.v --candidate rtl/mod10_counter_bug_wrap9.v `
  --output-dir runs\vd-diff --print-markdown
echo "exit=$LASTEXITCODE"      # 期望 1
```

**这条最值得看三处**：

1. **两边都没给合约、也没给测试计划**，工具自己准备——合约从基线 RTL 提**草稿**、
   计划由离线确定性规划器生成；
2. 报告里有一节「**凭什么这么说**」，列明计划来源、期望值证据等级、合约来源、
   可比检查项数、波形是否比对过；
3. 报告末尾有一节「**这次没覆盖到什么**」——包括"合约是自动草稿，所以
   「两侧不同」仍然可信，而「两侧一致」的覆盖范围可能因此变窄"。

**退出码**：`0` 一致 / `1` 不同 / `2` 未取得可比证据。**`2` 不是 `0`**：
它表示"没测出结论"，CI 里必须当失败处理。

---

## 4. 复现我们发布的每一个数字（约 2 分钟）

```powershell
python -m pytest -q                            # 期望 0 failed（具体条数见 CI 徽章）
python scripts/run_synthesis_matrix.py         # 期望 98/98 可综合
python scripts/run_pipeline_matrix.py          # 期望离线 AI 路径 15/15，每例证据等级 reference_model
python -m mypy                                 # 期望 Success: no issues found
python scripts/check_dead_code.py              # 期望未发现未可达代码
python scripts/check_doc_index.py              # 期望 docs/INDEX.md 里 95/95 条路径都存在
```

**条数为什么会和别人不一样**（这是正常的，别以为是坏了）：

| 装了什么 | 收集到的用例 | 说明 |
|---|---:|---|
| 只装 `.[dev]` | 约 686 | UI 冒烟（35 条）**不会被收集** |
| 再装 `.[ui]` | 约 721 | `test_ui_smoke.py` 需要 `streamlit` |

这两组测试是用 `pytest.importorskip` 跳过的：缺依赖时它们**静默地少收集**而不是报错。
"少测了"比"测失败"更危险，所以我们把数字写在这里，而不是让你去猜。

**本节全部命令都在干净虚拟环境里实测过**（2026-09-29）：`pip install -e ".[dev]"` 之后
`python -m pytest -q` 得到 **675 passed / 3 skipped / 0 failed**，`python -m mypy` 得到
`Success: no issues found in 61 source files`。如果这两条对不上，就是我们对不上。

---

## 5. 对不上怎么办（这比"通过"更有价值）

请把下面三样发给我们（附在 Issue 里即可）：

1. **命令原文**与 `exit code`；
2. `python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"` 的输出；
3. 出问题那条的原始产物：`.iverilog-ai/<matrix-name>/` 下的 `matrix.json` 与对应日志，
   或 `verify-diff` 的 `verify_diff.json`。

**如果数字对不上，请以你的运行结果为准**——本仓库的所有数字都是特定版本 Icarus 下的实测值，
换版本、换平台都可能不同。我们宁可知道差异，也不想要一个漂亮但不可复现的矩阵。

---

## 6. 明确的边界（不用去验证的，我们没声称）

- 不做时序签核、不做布局布线/比特流、不做上板验证；
- 不做代码覆盖率、不做形式化等价证明；
- 参考模型只覆盖 15 个内置案例，自定义设计只能回退到 AI 或人工期望值；
- "综合通过"只说明可映射到通用门级单元，**与功能正确性无关**；
- 行为对比只证明"在测试计划覆盖的激励范围内一致"，范围之外的一致它证明不了。
