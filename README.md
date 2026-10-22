# ICARUS 智测：RTL 功能验证工具

ICARUS 将在线模型的测试规划接入本地 RTL 仿真。用户选择案例或上传源码，确认端口、时钟和复位，再生成测试计划并执行。Icarus Verilog 负责编译和仿真，验证程序根据参考模型、向量期望值或结构化断言检查输出，保存日志与波形。

项目面向数字 IP 的模块级功能验证，提供 Streamlit 网页和命令行入口。源码仓库为 [TYOCT-13/iverilog-ai-lab](https://github.com/TYOCT-13/iverilog-ai-lab)。

## 主要功能

| 操作 | 功能 |
|---|---|
| 导入设计 | 支持多文件 RTL、头文件及顶层选择；提取接口草稿并执行编译预检 |
| 生成测试 | 将功能规格、验证目标和接口定义转换为受约束的 JSON 测试计划 |
| 执行仿真 | 自动生成测试台，按约定采样并记录期望值与实际值 |
| 自动补测 | 有独立判据时，Agent 根据已有观察继续提出输入，受轮数、请求和周期预算限制 |
| 审查与对比 | 提供静态规则审查、两份 RTL 的行为对比和 VCD 分析 |
| 导出结果 | 保存源码、接口、计划、测试台、报告、日志和 VCD，供复查与重放 |

## 安装与启动

首次使用需要 Git、Python、uv 和 Icarus Verilog。安装及 PATH 检查见 [Windows 首次安装说明](docs/reproduce_windows_setup.md)，异机操作与记录要求见 [复现指南](docs/reproduce_current.md)。Yosys 用于可选综合，GTKWave 用于可选波形查看。

```powershell
git clone https://github.com/TYOCT-13/iverilog-ai-lab.git
Set-Location iverilog-ai-lab
uv sync --locked --extra dev --extra ui --python 3.12
uv run python -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8600 --browser.gatherUsageStats false
```

打开 <http://127.0.0.1:8600>。首次会话默认选择在线模型，点击“进入配置”后填写服务地址、模型名称和密钥；已配置本机密钥文件时可按页面提示使用。打开网页和检查配置不会自动生成测试或请求模型。

无需模型服务时，可选择离线模式或本地调试。两者使用确定性规则，不代表在线模型的能力，也不要求填写 API Key 或模型名称。本地调试的 HTTP 服务启动方式见 [调试接口说明](docs/debug_interface.md)。

也可运行 `scripts/make_shortcuts.ps1` 创建本机启动、停止与控制面板快捷方式。快捷方式和本机工具路径不应直接复制到另一台电脑。

## 网页操作

1. 在“工作台”选择案例，或上传顶层及全部依赖源码。
2. 自定义 RTL 先确认接口并点击“校验接口”。编译预检失败时，按诊断补齐依赖或修正源码。
3. 填写验证目标，生成测试计划，核对输入过程和输出判据，再运行计划。
4. 检查实际比较数、期望值来源、结构化断言及波形，最后导出证据包。

“验证一份 RTL”“对比两份 RTL”和“学习模式”仅在工作台显示。其他页面分别提供规则审查、运行档案、工具设置、使用手册及项目概览。

## 命令行示例

执行案例自带的测试台：

```powershell
uv run python -m iverilog_ai run --rtl rtl/mod10_counter.v --testbench tb/tb_mod10_counter.v --top tb_mod10_counter
```

执行已有接口与计划：

```powershell
uv run python -m iverilog_ai plan-run --plan examples/simple_alu_plan.json --contract examples/simple_alu_contract.json --rtl rtl/simple_alu.v
```

工具默认自动检测 Icarus 与 vvp。找不到时，按 [工具路径说明](docs/reproduce_tool_paths.md) 设置本机实际路径。完整命令与结果字段见 [使用手册](docs/manual/01_beginner.md)。

## 结果与适用范围

运行完成只说明仿真进程结束。功能结论还需要有效检查及明确判据。支持的案例使用确定性参考模型复算期望值；自定义 RTL 没有参考模型时，可能使用 AI 或人工填写的期望值，需独立核对。

结构化断言与向量输出比对分别记录。输出比对一致时，仍可能存在断言告警；应同时查看报告中的“结构化断言”和交叉验证状态。没有期望值、参考检查或有效断言的运行，只能作为行为观察。

本项目不提供时序签核、布局布线、上板测试或形式化等价证明。功能场景与信号活动统计不等于 RTL 代码覆盖率。自定义源码执行环境也不构成完整安全沙箱。

## 技术报告与实验资料

- [当前技术报告与答辩材料](docs/competition/ic/technical_report/README.md)：实现、实验设置、结果和限制。
- [资料索引](docs/INDEX.md)：按任务查阅报告、实验原件及复现资料。
- [两模块完整策略对照](docs/experiment/agent_new_holdout_study_live_2026-10-05.md)：108 个登记任务，保留全部执行与请求记录。
- [历史八模块对照](docs/experiment/agent_feedback_study_live_2026-10-05.md)：与当前两模块实验分别报告，不合并分母。
- [判据改进实验](docs/experiment/protocol_oracle_improvements_2026-10-04.md)：FIFO 独立队列对照及 UART 位时序检查。

固定测试基准、模型生成测试与反馈 Agent 使用不同评价口径，不能把固定基准成绩直接归为模型效果。各批次的失败、资源消耗和适用范围见对应原始报告。

## 检查与贡献

```powershell
uv run python -m pytest -q
uv run python scripts/run_benchmark_matrix.py
uv run python -m mypy
```

测试结果以本次实际输出为准。历史云端检查按具体源码提交绑定，见 [发布检查记录](docs/experiment/multifile_ci_ppt_2026-10-21.md)。

贡献要求见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题报告方式见 [SECURITY.md](SECURITY.md)，变更过程见 [CHANGELOG.md](CHANGELOG.md)。项目为 Icarus Verilog 的非官方扩展，不代表其维护者立场。

## 许可证

本项目自研部分采用 Apache License 2.0。第三方工具、库和案例遵循各自许可证，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。模型服务配置与密钥不应提交到仓库、报告或录屏。
