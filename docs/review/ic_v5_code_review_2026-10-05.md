# IC Agent v5 零 API 代码复核记录

记录日期：2026-10-05。审查者为 Codex 子代理，不是独立真人；本记录不满足 H02，不是真人试用、第三方认证或异机复现。只读检查生产代码，复现副本保存在 `.iverilog-ai/ic-v5-code-review-20261005/`；未改写历史实验原件、未读取真实凭据、未调用外部 API。

结论：本次发现的两处证据绑定缺口、采样预检恢复问题和输入路径边界问题均已修复并复判。下面登记的最终源码没有本次范围内仍待处理的已确认问题；这份局部代理复核不代替全仓验收或新的在线实验。

## 范围与版本

本轮覆盖 `scripts/run_agent_comparison.py` 的 `--profile v3`、`scripts/summarize_agent_comparison.py`、Agent 计划调度，以及 `core/reference_model.py`、`core/testbench.py`、`core/pipeline.py` 的逐拍生成与证据连接。最后对 `ui/app.py` 的 Literal 缩窄和表格高度做了静态检查；没有执行浏览器交互、复跑完整回归或复核正式 PDF/PPTX，也没有重算、覆盖旧 v4 成绩。

检查时 Git HEAD 为 `572e145bc34426a7b8947d23d2a0a23f503658f1`，上述生产代码在脏工作区中。HEAD 不能单独代表本次被测代码；各机器回执记录实际源码 SHA。最终登记如下：

| 文件 | SHA-256 |
|---|---|
| `scripts/run_agent_comparison.py` | `8d283240e1c232ef0cb3a7053f945d1e604456eaf13455648c0868531f5d8287` |
| `scripts/summarize_agent_comparison.py` | `ef8ba4bdc7e256ac7ab0bab82abdc372cd4e9c7b0c1460e95c05d7eab383871f` |
| `ui/app.py`（仅末次收尾静态检查） | `f58e4bd57e2221daaa6db9b254b03c3eb1ff4c6dd5b55d516c319b954d279a8e` |
| `src/iverilog_ai/ai/agent.py` | `0b7758b0a5a3cc2a2f07fabfde1b3808fab860872c161df247a68f4b95da3c40` |
| `src/iverilog_ai/ai/provider.py` | `caf55116017e962743e03223ff978b13e69ba71b41e11113d16648e8e9763478` |
| `src/iverilog_ai/core/pipeline.py` | `3cf278b7df84f8d1e8d57786bc3b2485afab14ad5f1a1ce43b5eed657a9b9446` |
| `src/iverilog_ai/core/reference_model.py` | `bc5b8b4c2bad64541124724f05ecd5ffc3f286fcb72438e759f1445f27c360c1` |
| `src/iverilog_ai/core/testbench.py` | `17119e5851a95e0b065832e0aa03eaeebeb98b630722b66a28751ae7592c86c9` |

[前一阶段源码和原回执索引](../../.iverilog-ai/ic-v5-code-review-20261005/final-review-index.json)保留各阶段的源码与证据 SHA。[runner/summary 第一轮收尾复判](../../.iverilog-ai/ic-v5-code-review-20261005/final-runner-summary-check.json)再次核查合法控制和两份攻击副本，并确认默认 v3 为 60 行、5 策略、理论最多 72 请求；报告 profile 降级到 v2 被拒绝为 `comparison_profile_mismatch`。

最后收尾将 summary 局部变量 `key` 改名为 `execution_field`，比较字段和逻辑保持不变；runner 改为直接传入 `independent if v3 else append`，对应之前的 v3 参数与旧 profile 默认值；UI 的选择结果缩窄到两个 Literal，widget key 不变，未执行提案表显式 `height=180`。这些 diff 没有改变本轮核心或 Agent 的 SHA。

在新的 `final-root-r2/` 目录中再次复判：两份绑定攻击继续被拒绝，合法控制继续通过；before/XZ 两例重新补提并实际各执行 1 拍。上表的最终源码指纹及结果见 [r2 复判回执](../../.iverilog-ai/ic-v5-code-review-20261005/final-root-r2/receipt.json)和 [r2 采样补提回执](../../.iverilog-ai/ic-v5-code-review-20261005/final-root-r2/sampling-preflight-recheck-01.json)。旧回执未覆盖。全仓验收与 UI 非默认选择的浏览器检查由根代理另行记录，本记录不先行声明其结果。

## 发现与处理

### 1. 失败列表未绑定真实记录，可制造检出

修复前的 `verify_per_cycle_evidence` 已比较逐拍参考表、实际 RESULT records 和 stdout，但检出仍由另一个 `simulation.failures` 列表决定。

在真实 Icarus 执行的 `hs_bug_ready_ignores_out_ready` 的 3 拍空闲计划中，9 项检查全部通过。只对私有 `pipeline_result.json` 副本注入一条失败，并更新行级失败数量、失败周期与封存 SHA，保留 stdout、RESULT records、原执行 result.json、计划、参考表和测试台不变，汇总仍返回 `detected=true / evidence_verified=true`。

修复后从 stdout 重建 `ResultRecord` 与 `FailureRecord`，核对失败列表、失败总数、原执行结果和完成状态。旧反例返回 `evidence_unknown / detected=false`，错误为 `failures_disagree_with_actual_records`；合法控制仍为 `not_detected / evidence_verified=true`。

- [原复现回执](../../.iverilog-ai/ic-v5-code-review-20261005/failure-list-binding-01/receipt.json)
- [原始合法行](../../.iverilog-ai/ic-v5-code-review-20261005/failure-list-binding-01/control-row.json)、[攻击副本行](../../.iverilog-ai/ic-v5-code-review-20261005/failure-list-binding-01/attack-row.json)
- [修复后复判](../../.iverilog-ai/ic-v5-code-review-20261005/binding-recheck-01/receipt.json)

### 2. 测试台与参考表互相一致，仍可能脱离实际执行指纹

修复前将私有测试台副本追加一行注释，同时更新参考表 provenance、metadata 与封存 SHA，汇总接受该记录，尽管 `simulation.config.testbench_sha256` 仍是实际执行的旧文件指纹。这个反例证明封存文件之间的自洽不足以证明它们就是执行时的输入；本例没有改变逻辑或增加检出。

修复后强制比较测试台封存 SHA、执行 config 指纹和原执行 result.json 的指纹。旧反例返回 `evidence_unknown / detected=false`，错误为 `executed_source_hash_mismatch`。

- [原复现回执](../../.iverilog-ai/ic-v5-code-review-20261005/tb-binding-01/receipt.json)
- [修复后复判](../../.iverilog-ai/ic-v5-code-review-20261005/binding-recheck-01/receipt.json)

两处修复前 summary SHA 为 `3a02eb1e62beb14cb48482f2b9567b668ca6cf0411484d9a04e878b7c60f9e21`，第一轮修复复判 SHA 为 `23f61ec74dd99953fbe7f43f789746701c22e14f55a21bf16678d586dff8a872`。随后增加 profile 一致性守门的 `50fc964a…` 版本，以及仅修局部变量类型冲突后的最终 `ef8ba4bd…` 版本，都再次拒绝两份原攻击，合法控制仍通过。

### 3. 逐拍采样约束没有进入可恢复预检

Agent 的预检原先使用生成器默认的 `vector_end` 规则。两份 schema 合法的模型动作分别使用 `before` 相位和 `1'bx` 输入；预检都登记为 `passed`，随后实际 `per_cycle` 参考生成抛出 `PipelineValidationError`，仅用一次请求便以 `execution_error` 结束。两例均为 0 轮、0 条 failed_attempts，后续已准备的合法动作没有获得补提机会。

这不制造检出，但与本轮“尚未仿真的计划错误可以在剩余请求内修正”的目标不一致。修复前 Agent SHA 为 `d11498ec7222c9f4ed374ba6e2a23eefcb50d9efa9956e2c0c45c5d9e830ae4f`。

- [原复现回执](../../.iverilog-ai/ic-v5-code-review-20261005/sampling-preflight-01.json)
- 原轨迹目录：`preflight-before-01/`、`preflight-xz-01/`，均位于本次私有证据目录。
- [最终修复复判](../../.iverilog-ai/ic-v5-code-review-20261005/sampling-preflight-recheck-01.json)：两例均在第 1 次请求预检拒绝，分别登记 `unsupported_sample_phase` 和 `reference_plan_invalid`；第 2 次合法 after 动作真实执行 1 拍，第 3 次 stop。每例保留 3 请求、1 个 round、1 条 failed_attempts 和全部模拟 usage；没有把被拒绝动作记作仿真。

复判强制匹配最终 Agent SHA `0b7758b0a5a3cc2a2f07fabfde1b3808fab860872c161df247a68f4b95da3c40` 后才执行，执行前后源码不变。复判脚本为私有目录中的 `recheck_sampling.py`，没有外部 API。

### 4. 登记路径需要在读取前校验

静态检查发现原 `execute` 先计算注册输入 SHA，随后快照函数才拒绝绝对路径、父目录和越界解析。根代理已将 `registered_source_path` 放在任何 SHA/read 之前，并登记合同 canonical SHA。

复判中，仓库内合法 74 项原字节快照通过；绝对路径、`..`、Windows drive-relative 路径被拒绝；快照 copy 越界、清单 SHA 变化和登记摘要变化也被拒绝。没有用真实敏感文件验证路径边界。

[快照与路径回执](../../.iverilog-ai/ic-v5-code-review-20261005/snapshot-path-01/receipt.json)

## 实际执行的控制与负例

| 检查 | 实际结果 | 原始证据 |
|---|---|---|
| 72 次全局请求上限 | 使用真实 provider 构造和 HTTP stub；1 次模拟传输异常、1 次额外 `type` 字段、70 次自动时钟输入预检失败，恰好 72 次，无真实 API；48 个压力样本全部保留，22 个最终受全局上限约束 | [预算回执](../../.iverilog-ai/ic-v5-code-review-20261005/runner-budget-stub-01.json) |
| 无仿真不计检出 | 上述 48 行为 0 round、0 检出；每个策略仍保留 16 个登记缺陷样本；唯一缺失 usage 来自模拟传输异常 | 同上 |
| no-feedback 不泄露错误反馈 | 该组模型 state 的 `plan_error` 未出现；异常与请求仍留在轨迹 | 同上 |
| endpoint 原件误用于 v3 | 真实 51 项端点检查不能冒充 480 项逐拍检查，返回 `reference_sampling_mismatch` | [模式错配回执](../../.iverilog-ai/ic-v5-code-review-20261005/endpoint-binding-01/receipt.json) |
| 改参考表且更新 SHA | 实际记录没有同步改变时拒绝为 `actual_check_value_mismatch` | [绑定复判](../../.iverilog-ai/ic-v5-code-review-20261005/binding-recheck-01/receipt.json) |
| 改 run 为失败或截断 | 与原执行 JSON 不一致时拒绝为 `pipeline_disagrees_with_execution_result` | 同上 |
| independent 两个真实 episode | 第一次写入 42，第二次空输入经新实例复位后输出回到 0；2 拍刺激、4 拍候选隐式复位，另行执行参考审核；3 次模拟请求全部记账 | [合法控制](../../.iverilog-ai/ic-v5-code-review-20261005/independent-control-01.json) |

预算压力测试为专门构造的两重复、两 API 策略，共 48 行；不是计划中的 60 行在线成绩。stub 的 token 数为模拟值，不代表真实模型用量或费用。

## 基线逐拍检查口径

以 seed 0 在真实 Icarus 中执行四个正确模块，各运行 fixed、random、protocol_random，合计 12 次。每个策略均使用完整原计划和相同逐拍机制，参考表行数等于刺激周期，实际检查数等于周期乘输出数；12 次均为 0 失败。

| 模块 | 每策略刺激周期 | 输出数 | 每策略实际检查数 |
|---|---:|---:|---:|
| sync_fifo | 160 | 3 | 480 |
| uart_tx | 512 | 2 | 1024 |
| spi_master | 384 | 4 | 1536 |
| handshake_stage | 160 | 3 | 480 |

[12 次运行回执](../../.iverilog-ai/ic-v5-code-review-20261005/baseline-density-01/receipt.json)。执行前后相关源码 SHA 不变。向量分段数量仍随策略不同；同检查密度不表示刺激分布、实际搜索长度或接口调用数相同。本检查不证明模型更强，不是全部变体或所有种子的成绩，也不是形式等价证明。

## 证据范围与限制

本记录的实际仿真、机器检查与负例都是本地代理审查。没有真人评审签字，没有 H01/H02 补录，没有真实 API 成功率结论，没有正式新实验统计，也没有完整回归通过声明。根代理和其他工作者的测试结果不作为本代理亲自执行的测试计数。

被修改的攻击文件均是本次私有目录中新建的副本。原负例、修复后判定、合法控制分别保存，不能用修复后的拒绝结果替换修复前确实可通过的记录。全量回归、冻结提交和任何真实 API 执行由根代理另行记录。
