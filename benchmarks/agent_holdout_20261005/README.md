# 新模块留出资产与离线审查

这批资产新增 `credit_guard` 与 `rotating_arbiter`，不改旧四模块开发集、旧结果、Agent v6 提示词或提供器。每类有一个正确 RTL 和两个人工单点突变，共六个目标。实际模型评测由另一个入口在资产冻结后执行；本目录的离线审查结果不是 Agent 检出成绩，也不是独立人审。

## 资源与可见范围

`manifest.json` 使用 `agent-holdout-modules-v1`。`cases` 中的 `reference_rtl` 指向 `rtl/` 正确模块，`contract_path` 指向 `examples/` 显式合约，`spec_path` 指向 `spec/agent_holdout_20261005/` 的中文/英文功能规格。`targets/{case}/A.v` 是正确 RTL 的逐字节快照；`B.v`、`C.v` 各只替换登记的一个表达式，端口和其他所有字节不变。

Agent 仅接收功能规格与显式接口合约。`manifest.json`、源码、独立语义模型、突变标签、手工 witness 和审查结果不作为模型输入。功能规格中的正常时序例已对 A/B/C 实际执行，三者输出一致；规格没有缺陷标签或人工反例序列。

两类均无参数、10 ns 上升沿时钟、`rst_n` 异步低有效复位；每 episode 独立自动复位。**每次提案 / 每个 episode 计划最多 12 个向量**，所有实际 episode 共享整个任务的 **16 拍累计刺激上限**；累计接受 64 向量只是内部安全上限。逐拍 `sample_phase=after` 检查全部输出。请求/轮数服从执行状态，不在规格中写死单轮。`clk` 由执行器产生，输入仅接受已知且符合位宽的数值。信用归还端口使用 **`release_req`**：初版 `release` 是 Verilog 保留字，真实 Icarus 发现后修正；功能语义没有变化。

## 语义与判据

`semantics.py` 在 RTL 之前建立。信用模型使用事件差值加范围夹紧；仲裁模型使用请求位置到旧起点的模距离最小值。RTL 则使用条件分支和四套显式优先级 `case`；集成参考模型使用另一套循环列表选择。测试还有手工计算的固定输出序列、接口范围与 one-hot 不变量，避免把 RTL 算法照抄成判据。

`validation.py` 只运行本地 `iverilog -g2001 -Wall` 和 `vvp`，把真实端口逐拍打印到记录中。预期值在 Python 侧独立比较，不嵌入 DUT。复位检查包含不等待上升沿的异步断言、运行中复位以及重新开始的状态。

`tests/core/test_agent_holdout_assets.py` 不依赖旧实验私有目录，不读取 API 密钥，使用禁网 fixture。最终专项验收为 **28 passed，2.78 秒**（修正后首轮为 2.77 秒）；真实 Icarus **28 次编译执行、2296 个逐拍观测**。其中包括信用 8 状态 × 4 输入组合、仲裁 4 起点 × 16 请求 × 2 advance 组合、两类各 4 个确定种子的随机序列、复位/保持、四个手工 witness、非目标场景以及公开规格的正常时序例。长穷举序列是离线判据审查，不能计入 16 拍 Agent 评测，也不能当成 API 成绩。

随后按实际 Agent 默认值同步预算文案为每提案 12 / 累计接受 64 / 累计刺激 16 拍，RTL 和语义判据未改；相关文档、SHA 绑定与手工语义最小复查为 **6 passed，0.40 秒**。通用 `TestPlan` 的 200 向量上限与实际 Agent 的 64 累计接受上限分别登记。

四个 witness 均真实触发对应变体；每个变体还通过所登记非目标场景。每条突变的字节锚点、替换、唯一出现次数、偏移、源行、源/目标 SHA 和手工预期值都可在 manifest 中复核。缺陷源只改变目标表达式，不通过改正确判据获取成绩。

## 首次失败与最终证据

首次 `release` 编译错误保留在 `.iverilog-ai/holdout-assets-validation-20261005/initial-compile-failure/` 和同名 XML；其中有原始测试台、编译命令、返回值及 stderr。修正后的成功原件另存于 `corrected-first-validation/`，没有覆盖失败。集成参考对齐由另外的代理保存，不能把它算成本目录一次通过。

最终机器收据在本目录 `validation_receipt.json`，包含新源/合约/规格 SHA、各真实执行记录摘要及私有原件路径；技能门禁摘要在 `audit/`。独立辅助代码 `mypy --follow-imports=silent`：两个源码 0 error。

## 严格技能门禁的实际限制

使用了 [readable-verilog-generator SKILL.md](C:/Users/TYOCT/.codex/skills/readable-verilog-generator/SKILL.md) 与 dispatcher。其要求是 “Generated deliverables must pass the formatter-backed gate with zero errors and zero strict warnings.” 本轮确实运行严格门禁，结果 **未通过**，没有将其标为完成；项目已明确以本地 Icarus 为语义验证权威，并允许记录无法完成的附加风格门禁。

| 公开门禁 | credit_guard | rotating_arbiter | 解释 |
|---|---|---|---|
| compile | passed | passed | 仅 formatter AST/静态解析；不是实际编译证明 |
| ast | failed | failed | 模板一致性检查未通过；解析错误数为 0 |
| readability | failed | failed | 固定头部/注释排版/区域和通用操作预算等规则失败 |
| comment | passed | passed | 独立 comment gate；readability 的注释类规则仍存在失败 |
| naming | failed | failed | 冻结公共端口未采用 i_/o_ 前缀等要求 |
| profile | passed | passed | profile 选择检查，不代表所有 profile 规则通过 |
| testbench | not_requested | not_requested | 技能报告本身未执行；本项目独立 Icarus 测试另列 passed |
| toolchain | not_requested | not_requested | 技能报告本身未执行；本项目实际 Icarus 编译/运行另列 passed |

两份严格报告分别为 36 errors/0 strict warnings 和 115 errors/1 strict warning。没有调整命名、增加流水延迟或改 oracle 来迎合门禁，避免改变既定接口和本拍/下拍语义。文件名 A/B/C 按留出目标中性路径要求保留。

规格 JSON 与 RTL 端口交叉核验 `ok=true, issues=[]`。实际调用 `workflow.cli write-spec` 后因缺少规定的 **wavedrom@3.6.1 renderer** 失败，未发布声称已渲染的 SVG；功能 Markdown 和 WaveJSON 均保留为可读文本。依赖预检同时确认缺少 `erie-remote-ssh`，且本机未找到 readable Python/Script 依赖技能。按任务限制没有安装依赖、连接远程或调用 API，因此不声称完整技能链路、综合、时序收敛或硬件验证通过。

## 重放

在仓库根目录运行：

```powershell
& 'D:/Users/TYOCT/anaconda3/python.exe' -B -X utf8 -m pytest tests/core/test_agent_holdout_assets.py -q
& 'D:/Users/TYOCT/anaconda3/python.exe' -B -X utf8 -m mypy --follow-imports=silent benchmarks/agent_holdout_20261005/semantics.py benchmarks/agent_holdout_20261005/validation.py
```

不要复用首次失败或冻结成功证据的 `--basetemp`，pytest 会重建指定临时目录。新的重放应选择新目录。API/训练请求为 0，真人试用与独立人工审查尚未完成；新模块数量和人工突变规模也不足以证明统计显著或一般化能力。
