# 本机产物与历史目录

这些路径属于作者电脑的工作记录、运行产物或快捷方式，不随 Git 克隆分发。缺少它们不能写成已复现历史实验；资料索引只验收仓库内的材料路径。公开实验原件从 [资料索引](INDEX.md) 中相应版本的报告和原件包进入。

| 本机路径（相对原工作目录） | 用途与范围 |
|---|---|
| `.iverilog-ai/ic-agent-v5-evidence-20261005.zip` | 旧 v5 交接 ZIP；报告与哈希清单在仓库内，ZIP 本身未随 Git 提供 |
| `.iverilog-ai/ic-agent-v4-evidence-20261004.zip` | 旧 c7/v4 交接 ZIP，同上 |
| `.iverilog-ai/strategy-fair-5rounds/strategy_matrix.json` | 历史离线策略原产物 |
| `.iverilog-ai/strategy-online-flash/strategy_matrix.json` | 历史在线策略原产物；不能通过离线重放补造 |
| `.iverilog-ai/ablation-matrix/` | 消融矩阵运行目录；入口是 `scripts/run_ablation_matrix.py` |
| `.iverilog-ai/matrix-final/` | 旧手写测试台矩阵；新运行使用新输出目录 |
| `.iverilog-ai/pipeline-matrix/` | 离线管线矩阵运行目录 |
| `.iverilog-ai/synthesis-matrix/` | 可选 Yosys 检查运行目录 |
| `.iverilog-ai/external/manifest.json` | 历史第三方模块抓取清单；仅有报告不等于本机有全部原输入 |
| `.iverilog-ai/model-compare-*/`、`.iverilog-ai/online-experiment-real*/` | 历史模型调用产物，不属于干净克隆默认输入 |
| `Icarus 智测面板.lnk`、`启动网页演示.lnk`、`停止网页演示.lnk` | Windows 本机快捷方式；用 `scripts/make_shortcuts.ps1` 生成，含本机路径 |

原作者的其他本机记录：

- `G:\iai-evidence-pack-final[.zip]`、`G:\iai-evidence-pack[.zip]`：2026-10-01 的历史小包，不是当前完整程序包。
- `E:\FPGA_WORK\Ti60F225_DemoBoard_v4\10_Ti60f225_sc431hai2hdmi_demo\Ti60f225_sc431hai2hdmi_v3\normify-iverilog-ai-lab`：仓库外的旧结构数据库，历史统计为 157 模块、216 API、53 依赖、25 布局、9 条变更。它不是其他机器运行本项目的前置条件。

作者电脑上这些目录存在，不代表在另一台机器上可访问。新的运行结果应独立保存，不覆盖历史路径，也不能把生成目录内的示例记录算作真人试用。
