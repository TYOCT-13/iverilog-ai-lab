# 多模块 API Agent 预注册试验

## 版本入口

以下保留legacy五策略pilot的原口径，默认CLI仍使用该profile，不改变旧预算表。新增重复评测须显式 `--profile v2`，读取完整协议、使用七策略及三次重复；详细规则见 [v2评测计划](agent_comparison_v2_plan_2026-10-04.md)。旧60行原件与新目录隔离，不能在新版代码上运行后仍称其为历史冻结版成绩。

当前legacy只保留旧策略、目标路径和预算配置；其`rtl/sync_fifo.v`及参考模型已修复同拍读写计数，不能复现旧FIFO语义。历史复现必须整体检出原冻结Git快照及依赖，不能只替换一个旧DUT配合新参考模型。旧原始结果不追溯重写。

新版汇总逐字段核对预注册不可变行字段，预算或目标不一致直接拒绝。检出由runner与汇总共享的判定函数依据每轮实际结果和参考审核重新计算，不信任`detected`布尔值。逐轮保存pipeline结果、计划、合约、TB、仿真结果及工具日志SHA；汇总核对现存字节、计划、RTL SHA和观察值。材料缺失、状态冲突或摘要与原件不符记为证据未知，不增加检出；不会删除其分母。旧文件缺少新版证据指纹时不能获得新版严格证据认证，原历史报告仍单独保存。

无round的真实API拒绝或截断也不满足整轮严格可核资格，但任务仍在固定分母内；有限结果可单独描述，资格不能用来筛掉失败。新版可显式传`--thinking-mode enabled|disabled`，默认null表示未指定、采用服务商默认。该设置在首请求前写入运行设置并冻结SHA，不由prompt/profile哈希独自代表，跨模式不得合并。

这是自动化技术试验，不是真人试用，也不是独立人工审核。结果不预设优劣；失败、格式错误、预算耗尽和未完成样本均保留。默认是 pilot，只能支持流程与局部效果分析，不能据此宣称普遍提高检出率或保证比赛获奖。

## 冻结范围

入口 `scripts/run_agent_comparison.py` 默认使用 sync_fifo、uart_tx、spi_master、handshake_stage。每类取 benchmarks/manifest.json 顺序中的前两个缺陷及正确基线；每种策略运行一次。共 60 个策略样本、8 个独立缺陷。选择发生在 API 调用前，不按成绩重新挑缺陷。

五种策略：固定激励、种子随机激励、单次 API 提案、带仿真反馈 Agent、无仿真反馈 Agent。固定策略复用现有策略实验的模板；随机策略逐周期均匀采样非时钟、非复位输入，固定 seed 可复现。它不是协议感知随机生成器。单次与闭环使用相同动作 schema 和提示词，单次只允许一次提案；无反馈消融仅隐藏给模型的上一轮 observation，实际仿真记录、失败即停止、预算仍一致。

每个真实被测变体独立运行闭环，不先在正确基线上生成一个计划再把它称为“变体反馈”。API 只见接口合约、当前模块在 spec/common_cases.md 的一行说明、当前计划与允许的反馈，不见缺陷标签、触发描述或参考实现源码。现有规格说明较短，这是本轮明确限制。

同类共享累计刺激周期预算：FIFO 40、UART 40、SPI 64、握手 24。Agent 每轮重跑旧计划也计入预算，不只计算新增周期；复位开销不计入刺激预算。固定和随机归一化到整个周期预算，API 不自动填满预算。API 每样本最多 1/3/3 次请求，理论合计 84 次。实际停止可以更早。seed 是重复编号，不保证远程模型确定性。

## 判据与证据

每轮已经执行的计划另外在正确参考 RTL 回放，作为判据审核，不能把该结果反馈给搜索 Agent。回放周期单独统计，不计入搜索预算。参考出现任何假警，则整个样本不能作为有效检出；参考无法执行或没有独立检查也不可判定。编译失败、超时、零检查、缺少独立参考模型均不能当作检出。

每个缺陷最多计一次独立检出，同时保留逐重复样本统计。分母来自预注册，不因请求失败或预算耗尽缩小。多个失败日志条目不能当成多个缺陷。缺失 usage 保留为空，费用没有服务商账单时记 null，不把未知费用记为零。API 传输请求按样本累计一次，usage 按唯一 `sample:decision` 记录，不因参考回放重复累加。

执行前写 preregistration.json（含模块、缺陷、策略、预算和代码/输入 SHA256）。另写 run_settings.json，冻结 wire_api、endpoint_host、model、max_output_tokens、total_request_cap、超时、流式设置和工具路径，并引用预注册 SHA256；results.json 同时引用两个文件的 SHA256。这两个文件均在第一次请求之前落盘，且不含密钥。dry-run 显示这些非密钥设置，不读取密钥文件。

结果逐样本原子更新；Agent 自身还逐轮保存轨迹。中断或审计失败时，入口从已经落盘的 Agent 轨迹恢复请求、usage、实际刺激周期；search_cycles 使用轨迹的累计执行值，audited_round_search_cycles 是已有审核条目的周期，差值单列 search_cycle_accounting_gap，不能用审核失败把真实执行成本减为零。参考审核分别记录已返回执行周期和尝试周期。请求缺失 usage 的数量保留，未知费用不当零。已存在目录拒绝覆盖。中断后的未开始样本保留；重跑应使用新目录，不能把最佳结果拼成一轮。

## 运行

在仓库根目录运行，默认只显示计划，不读密钥、不发请求、不创建目录：

```powershell
python scripts/run_agent_comparison.py
```

仅运行真实 Icarus 基线，零 API 请求：

```powershell
python scripts/run_agent_comparison.py --execute --strategies fixed random --output-dir .iverilog-ai/agent-comparison-offline
```

经授权的付费 pilot 示例（模型与地址必须是实际服务配置；密钥只从指定本机文件读取）：

```powershell
python scripts/run_agent_comparison.py --execute --endpoint https://api.deepseek.com --model deepseek-flash --wire-api chat_completions --api-key-file C:/Users/TYOCT/OneDrive/api/ds-aic.txt --total-request-cap 84 --max-output-tokens 8192 --output-dir .iverilog-ai/agent-comparison-live-chat-v2
```

总 cap 是请求数量，不是人民币限额。默认 cap=0，所有 API 样本会明确记为 global_request_budget。脚本无自动重试；错误只记录类型，不保存密钥或远程错误正文。Icarus 路径可用 `--iverilog`、`--vvp` 显式配置。

### 2026-10-04 协议配置修正

首次 `.iverilog-ai/agent-comparison-live-20261004` 使用了 Provider 隐含的 `responses` 默认协议，与此前服务商成功联调使用的 Chat Completions 不一致，已停止。原目录及失败记录保留。入口现提供 `--wire-api chat_completions|responses`，默认显式传 `chat_completions`；使用真实 Provider 和 mock HTTP 传输测试实际请求路由，而不是只检查代码字符串。后续新目录属于修正运行，不能删除首次失败、与首次局部成绩拼接，或把新运行说成首次就成功。此协议修正本身没有进行付费请求。

后续正式实验需要更多经过复核的缺陷、至少 3–5 次重复、独立留出模块、更完整的规格和协议感知随机基线，并记录实际费用。真人试用与第三方人工审核仍需真实参与者另行完成。
