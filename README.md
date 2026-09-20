# Icarus 智测：AI 验证扩展

这是一个围绕 Icarus Verilog 开源生态构建的非官方 AI 辅助 RTL 验证工具。AI 负责提出测试场景和解释失败，Icarus Verilog 与自检 testbench 负责裁决功能是否正确。

## 当前进度

- 阶段一确定性验证闭环：已完成并有真实 Icarus/vvp 证据。
- 阶段二 AI 测试规划：离线 MockProvider、OpenAI-compatible provider、严格 JSON 校验和重试，以及“计划→testbench→Icarus/vvp”确定性流水线均已完成。
- 阶段三基准与评测：**15 个案例、83 个缺陷变体**，最近一次固定矩阵实跑 **83/83 检出、参考误报 0、不可判定 0**。常用 FPGA 案例（FIFO、UART、SPI、握手、去抖、PWM、多路选择器、同步复位、约翰逊计数器、上升沿检测器）均配有专门的边界 testbench 与缺陷基准。
- 阶段四演示材料：Streamlit 单页、申报大纲、演示脚本和公平评测方案已完成。CI 工作流见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)（Linux 与 Windows × Python 3.11/3.12 四组合，跑全量测试、基准矩阵与编码卫生检查）。
- 阶段五验证深度增强：内置案例参考模型校验、测试计划执行覆盖率摘要、失败原因解释、受控断言模板、失败周期波形摘要和 14 套常用案例 reference model 已完成；参数化 contract 与 testbench 实例化已接入。
- 阶段六 RTL 质量审查：已提供静态规则审查器、质量评分、JSON/Markdown 报告和网页下载；静态审查不替代 Icarus 仿真、综合或时序分析。
- 阶段七 VCD 自动分析：已提供本地 VCD 解析、信号列表、时间范围和变化统计；并已扩展到**波形语义结论**（沿统计、毛刺型不稳定、晚/早一拍相位检查）、参考波形与缺陷波形差异对比、失败周期对应时间窗。无需 GTKWave 也能生成波形摘要，GTKWave 作为可选人工复核工具；判据与噪声校准记录见 [docs/vcd_analysis.md](docs/vcd_analysis.md)。
- 阶段八权威预言机与离线调试接口：内置案例的期望值改由参考模型独立复算并覆盖 AI 数值（AI 期望值偏差单列为诊断指标），新增复位前初值观测和本地调试模型服务（无需 API Key、不联网）。
- 阶段九 RTL 静态审查扩展：规则增至 **44 条**，每条规则都有最小反例/正例用例，清单与噪声校准见 [docs/static_rules.md](docs/static_rules.md)。
- 阶段十参考模型全覆盖：**15 / 15 个内置案例**的参考模型已与 RTL 逐拍对齐（`SUPPORTED == AUTHORITATIVE`），因此每个内置案例的期望值都由确定性模型独立复算；对齐方法、采样口径与踩过的 8 个模型错误见 [docs/reference_model_alignment.md](docs/reference_model_alignment.md)。
- 阶段十一分层证据：新增 Yosys 综合证据层，把「仿真 / 综合 / 时序 / 比特流 / 上板」五层状态显式写入报告与网页，未做的层级标 `not_run`；综合不参与 PASS/FAIL 裁决，也不做时序签核。口径与实测结果见 [docs/layered_evidence.md](docs/layered_evidence.md)。
- 阶段十二行为级对比：自定义 RTL 与标准 RTL 跑**同一份** TestPlan，逐检查项与逐波形信号比对，命令行入口 `compare-rtl`；语义等价的重写（即使多出内部辅助变量）判为一致。判据与实测见 [docs/behavior_compare.md](docs/behavior_compare.md)。
- 阶段十三激励质量与证据标注：新增**信号活动覆盖率**（哪些信号动过 + 到达过多少种取值，由 VCD 推导，**不是**代码覆盖率，口径见 [docs/coverage.md](docs/coverage.md)）；期望值来源改为三态如实标注（参考模型复算 / AI 生成 / 未给出期望值）；两个真实模型的同口径对比已完成，检出率相同而 AI 期望值准确率相差 11 个百分点，见 [docs/experiment/model_comparison_2026-09-11.md](docs/experiment/model_comparison_2026-09-11.md)。
- 阶段十四开源协作与成本透明：新增 CI、Issue/PR 模板、行为准则、安全策略、引用文件与变更记录；新增**开源规约知识摄取**（从真实开源项目按固定提交实测编码约定，只存聚合统计与逐文件 sha256，不复制代码，见 [docs/opensource_conventions.md](docs/opensource_conventions.md)）；新增**未核验就留空的费用估算表**（价格留 `null` 而非填 0，见 `data/model_pricing.json`）。
- 阶段十五基准扩充与门禁加固：基准扩到 **15 个案例 / 83 个缺陷变体**（新增脉冲展宽器，含参考模型逐拍对齐与 3 个根因独立的缺陷）；新增**可复现的综合矩阵脚本**（`scripts/run_synthesis_matrix.py`，98 个变体）、**重复缺陷检测**、**编码损坏检测**与**未可达代码检查**（`scripts/check_dead_code.py`）。这轮门禁抓出四个真问题：一个重复登记的缺陷、两个被编码破坏的注释、两个从未渲染过的按钮（"读取模型列表"/"检查配置"），以及一份 150 行的死代码语义副本。变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 快速开始

在工程根目录执行（请按本机 Icarus 安装位置调整工具路径）：

```powershell
python -m pip install -e .            # 离线环境可加 --no-build-isolation
python -m iverilog_ai run `
  --rtl rtl/mod10_counter.v `
  --testbench tb/tb_mod10_counter.v `
  --top tb_mod10_counter `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe
```

命令返回 0 表示编译、执行和所有结构化检查均通过；返回 1 表示 testbench 发现失败或证据不足。每次运行会在 `.iverilog-ai/runs/` 下建立独立目录。已有结果可用下列命令重新渲染：

```powershell
python -m iverilog_ai report --result .iverilog-ai/runs/run-<id>/result.json --format html --output report.html
```

启动演示页面：

```powershell
streamlit run ui/app.py
```

页面规划器默认是**离线确定性规划器**：进程内按当前 DUT contract 生成激励，不需要密钥、
不联网、也不依赖任何服务，组合逻辑案例（如"简单 ALU"）与时序案例都能直接跑通。

波形查看（可选）：页面自带 VCD 解析与时间窗分析，**不依赖 GTKWave**；要用 GTKWave 人工复核时，
路径按「设置页手填 → `GTKWAVE_PATH` → PATH → 常见目录 → 从 iverilog 安装位置推断」解析，
因此官方 Icarus Windows 安装包（GTKWave 在同级 `gtkwave\bin\`）通常不需要手工配置：

```powershell
$env:GTKWAVE_PATH = "D:\iverilog\gtkwave\bin\gtkwave.exe"   # 需要时显式指定
```

在无 API Key、无网络的环境下联调 HTTP 接口层（本地调试模型，仅监听回环地址）：

```powershell
python -m iverilog_ai.ai.debug_server
```

然后在网页「AI 接口设置」中选择「本地调试模型」即可。详见 [docs/debug_interface.md](docs/debug_interface.md)。

> Windows 终端中文：脚本输出为 UTF-8。若要把输出重定向到文件（`... > out.txt` 或
> `Tee-Object`），先设置 `$env:PYTHONUTF8="1"`（或 `$env:PYTHONIOENCODING="utf-8"`），
> 否则 Python 会按系统 ANSI 代码页写文件，用 UTF-8 打开时显示为乱码。

离线测试计划示例（按 DUT 合约生成，不需要密钥也不联网）：

```powershell
python -c "from iverilog_ai.ai import offline_provider, plan_tests; from iverilog_ai.core.contracts import DutContract; c=DutContract.from_json(open('examples/simple_alu_contract.json',encoding='utf-8').read()); print(plan_tests('覆盖进位与边界', c.module, provider=offline_provider(c)).model_dump_json(indent=2))"
```

> 不传 provider 时 `plan_tests` 会回落到 `MockProvider` 的**写死演示计划**（`design="demo"`，
> 固定驱动 `rst_n`）——它只用于最小可运行示例，拿去跑没有 `rst_n` 的组合逻辑设计会被
> 合约校验拒绝。要按真实设计生成，请显式传 `offline_provider(contract)` 或在线 provider。

从显式 DUT 合约和 AI 测试计划生成受控 testbench 并执行：

```powershell
python -m iverilog_ai plan-run `
  --plan examples/simple_alu_plan.json `
  --contract examples/simple_alu_contract.json `
  --rtl rtl/simple_alu.v `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe
```

运行完整固定向量基准矩阵并生成 JSON/Markdown 摘要：
```powershell
python scripts/run_benchmark_matrix.py --project-root . `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe
```

运行 5-seed fixed/random/AI 公平基线（AI 使用离线 MockProvider）：

```powershell
python scripts/run_strategy_experiment.py --project-root . --seeds 5 `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe
```

实验逐次记录输出到 `.iverilog-ai/strategy-experiment/strategy_matrix.json`。

让自定义 RTL 与标准 RTL 跑同一份测试计划并做行为级对比：

```powershell
python -m iverilog_ai compare-rtl `
  --plan examples/simple_alu_plan.json `
  --contract examples/simple_alu_contract.json `
  --user-rtl rtl/simple_alu.v `
  --reference-rtl rtl/simple_alu.v `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe
```

退出码：`identical` → 0；`different` → 1；无法判定 → 2。详见 [docs/behavior_compare.md](docs/behavior_compare.md)。

## 开源生态成果

- Icarus Verilog 外部验证扩展；
- 可复用测试计划格式与严格校验；
- 四类 RTL 缺陷基准集（详见 `benchmarks/manifest.json`）；
- 自动回归、CI 和离线报告工具；
- 中文案例、教程和参赛材料。

## 参与贡献

- 想先看项目能做什么：[docs/project_overview.md](docs/project_overview.md)（含 10 页 PDF）
- 想审一遍"要求 / 计划 / 尝试 / 现状"：[docs/delivery_review.md](docs/delivery_review.md)（交付审核文档，含需要拍板的 7 个点）
- 想动手试一遍：`docs/trial/` 的[试用任务卡](docs/trial/task_card.md)，约 40 分钟、无需密钥
- 贡献流程、案例成套提交要求与提交前必须通过的命令：[CONTRIBUTING.md](CONTRIBUTING.md)
- 变更记录（含各阶段的误报校准与修复原因）：[CHANGELOG.md](CHANGELOG.md)
- 安全问题报告渠道（**请勿开公开 Issue**）：[SECURITY.md](SECURITY.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 引用信息：[CITATION.cff](CITATION.cff)

## 项目边界

- 本项目不是 Icarus Verilog 官方项目，也不代表其维护者立场。
- 本项目不修改、复制或重新分发 Icarus Verilog 源码。
- AI 输出不能代替编译与仿真证据。
- 固定案例和经用户确认 contract 的自定义 RTL 均可执行；自定义 RTL 仍不等同于不可信代码安全沙箱。
- 模型密钥不得写入仓库；网络 provider 只有显式设置 `IVERILOG_AI_ALLOW_NETWORK=1` 才会请求。
- 不自动覆盖原始 RTL，不自动提交 GitHub Issue/PR。

详细范围见 [PROJECT_SCOPE.md](PROJECT_SCOPE.md)，真实验证记录见 [docs/verification_report.md](docs/verification_report.md)，参赛材料见 `docs/competition/`、`docs/demo/` 和 `docs/experiment/`。

## 许可证

本项目自研部分采用 Apache License 2.0。第三方工具、库和案例遵循各自许可证，详见 `THIRD_PARTY.md`。
