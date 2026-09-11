# 贡献指南

感谢你对 Icarus 智测（`iverilog-ai-lab`）感兴趣。本文说明这个项目的边界、如何搭起开发环境、以及什么样的贡献会被接受。

## 一、先理解项目的边界

这个项目有一条不可协商的设计原则，所有贡献都必须遵守：

> **AI 提出测试假设，开源仿真器作出判决。**

具体含义：

- PASS/FAIL **只能**由 Icarus Verilog 的编译/仿真结果与结构化断言决定；
- AI 的输出（测试计划、期望值、失败解释）**不得**参与裁决；
- 模型输出**不得**进入命令、路径或 Verilog 代码；
- 内置案例的期望值必须来自与 RTL **逐拍对齐**的确定性参考模型。

如果你的改动让"模型自评"或"模型给出的期望值"影响了结论，这个改动会被拒绝，无论它看起来多方便。

## 二、开发环境

```powershell
# 1. Python 3.11+
python -m pip install -e .
python -m pip install pytest

# 2. Icarus Verilog（必需，判决权威）
#    Windows: 安装包 https://bleyer.org/icarus/
#    Linux:   sudo apt-get install iverilog
#    工具位置由 core.toolchain 自动探测，也可用环境变量指定：
#      $env:IVERILOG_PATH = "D:\iverilog\bin\iverilog.exe"
#      $env:VVP_PATH      = "D:\iverilog\bin\vvp.exe"

# 3. Yosys（可选，仅分层证据层需要）
python -m pip install yowasp-yosys

# 4. 环境自检
python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"
```

## 三、提交前必须通过

```powershell
python -m pytest -q                              # 全量测试
python scripts/run_benchmark_matrix.py           # 基准矩阵：14 参考全过、80/80 检出、0 误报
python scripts/strip_bom.py --check              # 源码不得含 UTF-8 BOM
```

CI 会在 Linux 与 Windows、Python 3.11/3.12 上跑同样的命令。**如果基准矩阵出现误报或漏检，先修代码而不是改期望。**

装了 Yosys 的话建议顺手跑一次综合矩阵（未装会明确报 `unavailable`，不算失败）：

```powershell
python scripts/run_synthesis_matrix.py           # 94 个变体（14 参考 + 80 缺陷）逐个综合
```

## 四、各类贡献的要求

### 新增基准案例（最常见）

一个案例必须**成套**提交，缺一项都不完整：

| 文件 | 要求 |
|---|---|
| `rtl/<case>.v` | Verilog-2001，首行 `` `timescale 1ns/1ps `` |
| `examples/<case>_contract.json` | 显式端口方向与位宽、时钟、复位；参数化要写进 `parameters` |
| `spec/<case>_spec.md` | 行为规格（含边界条件） |
| `tb/tb_<case>.v` | 功能 testbench，每条断言输出 `IVERILOG_AI_RESULT {json}` |
| `tb/tb_<case>_boundary.v` | 边界 testbench |
| `benchmarks/manifest.json` | 加入 `categories`，并为每个缺陷补 `defects` 条目 |
| `src/iverilog_ai/core/benchmark_cases.py` | 在 `CASE_TABLE` 里补 `rtl` / `testbench` / `top` **三件套**；漏了这一行，基准矩阵会直接报错（校验先于执行），不会静默漏跑你的案例 |
| `src/iverilog_ai/core/reference_model.py` | 加入 `SUPPORTED`、`AUTHORITATIVE`、`INPUT_DEFAULTS`，并实现 `_DesignState.step` |
| `tests/core/test_reference_model_alignment.py` | 加入 `ALIGNED_CASES`，通过逐拍对齐 |

**参考模型必须逐拍对齐才能进 `AUTHORITATIVE`**。对齐方法见 `docs/reference_model_alignment.md`——里面记录了 8 个真实踩坑（核心是 IEEE 1364 非阻塞赋值在同一时刻读到旧值）。

### 新增缺陷变体

每个缺陷必须有**独立根因**，不接受同一原因换个写法的重复变体。提交时说明：

- `trigger`：什么条件触发；
- `expected` / `actual`：期望与实际；
- 哪个 testbench 的哪条检查能检出它（给出实跑的记录行）。

如果某个缺陷在当前向量式 testbench 下**原理上不可观测**（例如只在时钟周期中间显现），不要注册它——在 PR 里说明原因即可。

### 新增静态规则

规则必须：

1. 在 `static_review.py` 的 `_RULE_REGISTRY` 中声明，且带 `source`（来源依据）；
2. 在 `tests/core/test_static_review_rules.py` 的 `RULE_CASES` 中配**最小反例**（必须命中）与**最小正例**（必须不命中）；
3. 通过噪声校准：对仓库内全部 RTL 跑一遍，确认没有 error 级误报。校准过程写进 `docs/static_rules.md`。

宁可漏报也不要误报——被误报淹掉的规则集等于没有规则集。

### 新增 AI 提供商

只需要实现既有的 provider 接口。注意：**provider 不得绕过校验链**（Schema → 合约匹配 → 参考模型复算 → 模板化断言）。默认必须是离线的，网络请求只在显式设置 `IVERILOG_AI_ALLOW_NETWORK=1` 后发起，且不得在仓库内保存凭据。

## 五、代码风格

- Python：类型标注 + `from __future__ import annotations`；面向用户与文档的注释用中文；
- 注释写"**为什么**"而不是"做了什么"——例如"这里必须用旧值，因为非阻塞赋值……"；
- 新增能力必须配测试；纯文档改动不需要；
- 不要引入新的重量级依赖。当前运行时依赖只有 `pydantic`（必需）与 `streamlit`（可选 UI）。

## 六、编码与换行

**源码文件不得带 UTF-8 BOM。** Windows 上 `Set-Content -Encoding utf8` 会写入 BOM，而 Python 的 `ast.parse` 与 `json.loads` 不容忍它。提交前跑一次：

```powershell
python scripts/strip_bom.py
```

仓库使用 `.gitattributes` 统一换行符。

## 七、安全问题

**不要在 Issue、PR、提交或文档里粘贴 API 密钥。** 发现凭据泄露请按 `SECURITY.md` 的流程私下报告。

## 八、许可证与出处

- 本项目自研部分采用 Apache-2.0；
- **不得提交第三方代码**。参考开源资料时只吸收工程原则，并在文档里标注来源；
- 新增第三方依赖必须同时更新 `THIRD_PARTY.md` 与 `docs/competition/opensource_resource_list.md`，写明版本、来源、许可证与关键义务；
- 不得提交无权再分发的图片、数据集或音视频素材。

## 九、提交信息

提交信息用中文，说明**改了什么、为什么**。如果改动影响可核验结论（基准矩阵数字、测试数量、对齐覆盖），必须在提交信息里给出前后数字。
