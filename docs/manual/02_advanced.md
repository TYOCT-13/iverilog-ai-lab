# 进阶手册 · 把它用进你自己的流程

面向：**已经跑通入门手册**，现在想用自己的 RTL、自己的目标，或者想在脚本/CI 里用它的人。

---

## 1. 自定义 RTL：三步上桌

1. **上传 RTL**：网页 → 概览页的"自定义 RTL"；或命令行直接指定路径。
2. **校验合约（DUT contract）**：合约声明端口方向、位宽、时钟与复位。
   - 网页：验证页 → 合约编辑器（表格或 JSON，双向同步）→ 点"校验自定义 contract"；
   - 命令行：`examples/<case>_contract.json` 就是模板，字段含义见下。
3. **生成计划并执行**：与内置案例完全相同的流程。

```json
{
  "module": "my_dut",
  "parameters": {"WIDTH": 8},
  "ports": [
    {"name": "clk",   "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "d",     "direction": "input",  "width": 8},
    {"name": "q",     "direction": "output", "width": 8}
  ],
  "clock": {"signal": "clk", "period_ns": 10},
  "reset": {"signal": "rst_n", "active_level": 0, "synchronous": false, "assert_cycles": 2}
}
```

**合约不是可选项**：端口名写错（把 `enable` 写成 `en`）是最常见的失败原因，工具会在执行前
直接拒绝，而不是生成一份跑不通的 testbench。

### 编译选项

```powershell
iverilog-ai run --rtl dut.v --testbench tb_dut.v --top tb_dut `
  --include-dir ./inc --define WIDTH=16 --define SYNTHESIS
```

网页在**验证页**有对应的"编译选项"输入框（宏定义、include 目录，逗号分隔）。

---

## 2. 三种入口怎么选

| 你想做的事 | 用哪个 | 命令 |
|---|---|---|
| 只想跑一份已有的 testbench | `run` | `iverilog-ai run --rtl ... --testbench ... --top ...` |
| 有测试计划 JSON，想生成 testbench 并裁决 | `plan-run` | `iverilog-ai plan-run --plan ... --contract ... --rtl ...` |
| 有两份 RTL（自己写的 vs 标准实现），想知道行为是否一致 | `compare-rtl` | `iverilog-ai compare-rtl --plan ... --contract ... --user-rtl ... --reference-rtl ...` |
| 只想看代码质量（不仿真） | `scripts/review_rtl.py` | `python scripts/review_rtl.py rtl/pwm.v` |

退出码是给脚本用的契约：`run` → 0 通过 / 1 有失败；`plan-run` → 0/1，输入问题 2；
`compare-rtl` → **0 一致 / 1 不同 / 2 无法判定**。

---

## 3. 结构化断言：把"显然的规矩"写死

测试计划里可以带五种受限模板（**不接受自由 Verilog/SVA 代码**）：

| 模板 | 用途 | 字段 |
|---|---|---|
| `signal_equals` | 该信号在**整个采样序列**里都等于某值 | `signal`, `value` |
| `signal_stable` | 连续 N 拍保持不变（N 至少 2；N=1 恒真，等于没有检查） | `signal`, `cycles` |
| `never_high` | 整个序列里从未为高 | `signal` |
| `signal_sequence` | 采样序列正好等于给定的取值序列 | `signal`, `values`（`cycles` 可省略，省略时等于 `values` 长度） |
| `signal_implies` | when 条件成立后，within N 拍内 then 成立 | `when_signal`, `when_value`, `then_signal`, `then_value`, `within_cycles` |

> ⚠️ **`signal_implies` 没有 `signal` 字段**。它只有 when/then 两个信号名，多写 `signal`
> 会被严格校验拒绝。2026-09 复核发现：这条"常见错误"其实是**提示词自己写错了**
> （提示词里列出 `signal_implies{kind,signal,...}`，而校验器不接受 `signal`）——模型只是
> 照着提示词写。现在提示词由 `ai/schema.py` 的字段表直接渲染，
> `tests/ai/test_planner.py` 断言"提示词允许的字段 == 校验器接受的字段"，两边不可能再漂移。
> 同一个复核还发现 `signal_implies` 当时**根本无法通过校验**（写 `signal` 报不支持字段，
> 不写又报 `signal` 必须是合法标识符），已一并修好。

> ⚠️ **`signal_implies` 缺 `when_value`/`then_value` 时永远匹配不上**（缺省值是 `None`，
> 而采样值不会是 `None`），断言会静默变成"空检查"。要真的检查就写全取值。

> 采样值是 Verilog 位串（`'0000'`），断言里的 `value` 写整数（`0`）即可——比较按**值**
> 进行，`'0000'` 与 `0` 相等；`x`/`z` 是不定值，只与同形的不定值相等，不会折算成 0 蒙混过关。

**断言是按"该信号的整个采样序列"判定的**，没有作用域概念，因此只有真正的全局不变量
（"永不为高"、"始终等于某值"、"req 之后必有 ack"）才适合写成断言。写之前先想清楚它在
**整个仿真过程**里是否都成立——本仓库曾经自动推荐过 5 条断言，复核时发现全部不成立
（详见 `src/iverilog_ai/core/rule_assertions.py` 的说明），因此推荐表已清空。

---

## 4. 批量与回归

```powershell
# 全量测试（含真实跑 Icarus 的端到端用例）
python -m pytest -q

# 固定矩阵：15 参考 + 83 缺陷，逐项实跑，产出 JSON/Markdown
python scripts/run_benchmark_matrix.py

# 综合矩阵：98 个变体逐个跑 Yosys（未装会明确报 unavailable）
python scripts/run_synthesis_matrix.py

# 离线 AI 路径矩阵：15 个案例逐个"规划 → 生成 testbench → 判决"
python scripts/run_pipeline_matrix.py
```

产物都在 `.iverilog-ai/<矩阵名>/` 下，`matrix.json` 是给脚本读的，`matrix.md` 是给人看的。

---

## 5. 接进 CI

```yaml
- run: python -m pip install -e . pytest mypy yowasp-yosys
- run: python -m pytest -q
- run: python scripts/run_benchmark_matrix.py      # 缺陷检出回归
- run: python scripts/run_pipeline_matrix.py       # AI 路径回归
- run: python -m mypy && python scripts/check_dead_code.py && python scripts/strip_bom.py --check
```

CI 需要 Icarus：Linux `apt-get install iverilog`，Windows `choco install iverilog`，
或设 `IVERILOG_PATH` / `VVP_PATH`。项目自带的
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) 就是照这个写的。

---

## 6. 在线模型（可选）

```powershell
$env:IVERILOG_AI_API_KEY = "sk-..."        # 只走环境变量，不写入任何文件
$env:IVERILOG_AI_ALLOW_NETWORK = "1"       # 网络请求需要显式允许
```

网页 → 设置页 → 规划器选"在线 API" → 填 Base URL / 模型 / 密钥 → 可先点"检查配置（不调用模型）"。

**三条纪律**：密钥不进仓库、不进报告、不进日志；超时/限流不自动重试（避免放大费用）；
AI 写的期望值只作诊断，判决永远由 Icarus + 参考模型给出。

---

## 7. 想让结果更可信，做这四件事

1. 用**边界 testbench**（仓库里 `tb/tb_<case>_boundary.v` 就是范例），别只测"正常流程"；
2. 期望值尽量来自**参考模型**或人工确认的合约，而不是模型自己写；
3. 看**信号活动覆盖率**：取值覆盖低说明激励太弱（实测弱激励下同一个计数器取值覆盖只有 6%）；
4. 把 `report.md`、`result.json`、`waveform.vcd` 一起归档——三者对得上才叫证据。
