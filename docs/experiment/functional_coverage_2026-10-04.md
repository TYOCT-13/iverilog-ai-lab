# 功能场景覆盖与 Agent 反馈

本轮实现将“计划里写了什么”与“执行器实际观察到了什么”分开。覆盖结论由 Python 确定性规则计算，模型只能看到缺口并追加激励，不能修改覆盖项、判据或结果。

这是**有限功能场景覆盖**，不声称语句、分支或代码覆盖率，也不代替参考判据的功能正确性检查。输入尝试、输出状态、协议序列分别标注。输入请求命中不代表请求已被接受，覆盖命中不代表不存在缺陷。

## 证据来源

`VerificationPipeline.run(..., capture_observations=True)` 在原有 testbench 采样点读取实际输入与输出，每个激励周期产生一条 `IVERILOG_AI_OBSERVATION`。读取动作不改变输入、等待时序、断言数量或原判定。`observed_samples.json` 记录：

- `cycle`、`time_ns`、`test_id`、`sample_phase`。
- 合约全部输入与输出的定宽二进制位串；X/Z 原样保留。
- 计划、合约、实际 testbench、RTL 的原始文件 SHA256。
- 预期周期、实际周期、执行完整性与解析错误。

功能覆盖再次核对这些 SHA、计划与合约的内容、端口宽度、逐周期顺序、时刻与输入保持语义。它还要求本次实际 vvp 进程正常完成，核对 `simulation.config.observed_samples.sha256` 与 packet 原始字节，并从本次 `simulation.run.stdout` 重新解析整份 packet。两份 packet 必须完全一致，不能只核对输入文件 SHA。`before` 采样不套用沿后模型；缺行、重复、乱序、相同时间戳、相邻周期时间不符或工件不匹配时，覆盖整体为未知。没有逐周期采样时，不从 VCD 的时间戳末值或向量端点补猜完整协议。

这一绑定修复来自代理审计的真实复现：初版只核对四项输入 SHA，手动把 FIFO idle 采样的 full 改为 1 可以制造覆盖命中；移除 `simulation.run` 也没有被拒绝。现版保存 packet 的执行期 SHA，并以本次真实进程 stdout 重算核验。只改 packet 会被 SHA 拒绝，连 SHA 元数据一起改仍会被 stdout 比对拒绝。无 run、未完成、超时或截断不能产生覆盖命中。功能断言失败与进程执行失败分开：vvp 正常完成且真实采样完整时，失败 RTL 的已观察场景仍可统计，正确性失败不会被覆盖结果掩盖。

自动初始复位不在场景统计周期内。边沿前的寄存状态仅使用连续且无复位的上一沿后实测样本；首个激励周期不根据合约推定复位已经成功。因此，首拍直接启动而未观察到此前 idle 时，可以命中“请求尝试”，不能自动命中“接收开始”。

## 已审计的覆盖配置

当前只支持四种内置合约的固定配置：FIFO `DATA_WIDTH=8, DEPTH=4`，UART TX `CLKS_PER_BIT=4`，SPI `WIDTH=8`，握手缓存 `WIDTH=8`。端口名、方向、位宽、符号属性、posedge 时钟、低有效异步复位也必须符合已审计配置。未审计的参数或合约返回 `unsupported`，而不是将未知设计当成内置模块。

调用方还必须显式选择内置证据策略。外部 `qualified_baseline_differential` observer 保持原有类型与判据，不因模块同名而启用本表。外部判据与内置覆盖的证据等级不能混用。

| 模块 | 覆盖项 | 严格含义 |
|---|---|---|
| FIFO | `fifo.empty` / `fifo.full` | 非复位沿后的空、满标志分别被真实观察到 |
| FIFO | `fifo.read_request` / `fifo.write_request` | 实际输入端口出现读、写请求；只报告尝试 |
| FIFO | `fifo.read_empty_attempt` / `fifo.write_full_attempt` | 上一实测空、满状态与当前读、写输入形成边界尝试 |
| FIFO | `fifo.simultaneous_request` | 当前实际输入同时请求读写；不代表两项都接受 |
| UART TX | `uart.request` / `uart.idle` / `uart.busy` | 请求输入或 idle、busy 输出状态被实际观察到 |
| UART TX | `uart.frame_start` | 前一实测 idle、本拍请求以及沿后 busy=1、tx=0 共同成立 |
| UART TX | `uart.busy_request_attempt` | 前一实测 busy 与本拍请求构成忙时请求尝试 |
| UART TX | `uart.complete_frame` | 从实测开始连续 41 拍，8N1 每位 4 拍、数据来自该次实际请求，终点 busy 释放；缺任一必要样本不命中 |
| SPI | `spi.request` / `spi.busy` / `spi.busy_request_attempt` | 分别记录请求、busy 状态及忙时请求尝试 |
| SPI | `spi.clock_transition` / `spi.done` | 连续样本的 SCLK 切换与 busy 下降、done 上升被观察到 |
| SPI | `spi.complete_transfer` | 实测请求后连续 16 拍、SCLK 交替切换 15 次、MOSI 每拍已知、最后 busy=0 且 done=1；不评价 MOSI 数据正确性，也不声称标准 SPI 时序合规 |
| 握手缓存 | `handshake.request` / `handshake.backpressure` | 请求输入，或 out_valid=1 且 out_ready=0 的实际状态 |
| 握手缓存 | `handshake.stalled_pair` | 相邻实测样本都受反压、有效且数据为相同已知值；只证明这对样本 |
| 握手缓存 | `handshake.output_transfer_condition` | 上一实测有效数据与当前真实 ready 构成内置寄存输出契约下的出端传输条件 |
| 握手缓存 | `handshake.refill_condition` | 同一传输条件下，本拍又有已知的新输入请求；不声称数据交接正确 |

FIFO 同时接受读写后的占用量已在另一并行任务中修为净 0。本模块没有用参考模型计数来“制造”空满状态，边界覆盖依据实际 full/empty 输出，因此统计不依赖旧基线的错误计数语义。旧 pilot 仍属于原冻结版本，不追溯改写。

## 三种覆盖状态

- `observed`：确定性条件命中，保存第一次命中的实际采样证据及周期。
- `missing`：完整有效的本次执行中，该有限条件没有命中；不代表永远不可达。
- `unknown`：候选场景缺少必要观测、必要位为 X/Z，或整体执行证据不完整。

已知条件明确为假时，不需要猜测其他无关的未知条件；只有必要条件全部为已知真时才命中。例如，明确没有 start 的采样不是一次 UART 请求，即使无关数据含 X。反之，start 本身为 X 不能计为请求。

完整帧开始后，预算在帧结束前耗尽时，完整帧覆盖是未知，而不是完整帧命中。SPI 和 UART 的完整序列使用中间每一周期，不把最后一条断言或最终 VCD 状态当成全帧证据。

每个 bin 包含 `id/kind/definition/status/first_evidence`。首次证据保存原始输入、输出、采样时刻、测试名称与周期；跨周期规则另外标明前态取自 `previous_after_sample`。顶层保存覆盖配置与定义 SHA、采样工件 SHA、各状态的 bin 列表与计数。

## Agent 接口和消融

`run_verification_agent(..., include_functional_coverage: bool = True)` 保持旧调用可用。支持内置配置时，无论是否把覆盖发给模型，都收集同一真实逐周期样本并将完整覆盖保存到每轮 `functional_coverage`；普通内置 observation 同样保留完整执行事实。覆盖范围是本轮重新执行的整个计划，不把旧向量重复执行算成新增覆盖收益。

模型仅收到 `compact_model_feedback`：bin ID、种类、短定义、状态、首次及末次命中周期、缺失/未知列表与计数。41 拍 UART 等完整证据数组仅留在本地轨迹，不送到 API。

| 策略开关 | 模型后续 observation | 真实采样与轨迹 |
|---|---|---|
| `include_feedback=True, include_functional_coverage=True` | 运行摘要与紧凑覆盖 | 完整保留 |
| `include_feedback=True, include_functional_coverage=False` | 运行摘要，删除功能覆盖字段 | 完整保留 |
| `include_feedback=False` | `None` | 完整保留 |

三种策略的首次请求 schema、spec 和 prompt 相同；后续仅按开关改变可见 observation。Prompt 版本为 `verification-agent-v3-functional-coverage`。模型返回预期输出、覆盖结论或额外命令仍会被现有严格动作 schema 拒绝。

## 已执行验证

使用仓库现有 RTL、真实 Icarus 12.0 和确定性 Scripted Provider，没有发真实 API 请求，也没有训练模型。

```powershell
& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m pytest -q `
  tests/core/test_functional_coverage.py tests/ai/test_agent.py `
  tests/core/test_external_agent.py tests/core/test_agent_export.py `
  --basetemp .tmp-codex/coverage-bound-execution-20261004

& 'D:/Users/TYOCT/anaconda3/python.exe' -X utf8 -m mypy `
  src/iverilog_ai/core/functional_coverage.py src/iverilog_ai/ai/agent.py
```

绑定修复后的定向回归：**102 passed，13.19 秒**；新增覆盖源码的 mypy 无问题，先前两个源码的 mypy 同样通过。测试包含：

- 四种内置模块的弱激励与完整、边界激励区分。
- UART 的连续 41 拍证据、SPI 中间切换与单拍 done，以及握手反压与省略输入保持。
- X/Z 不计命中，零采样、缺失、重复、乱序、同一时刻、错误宽度、SHA 错误均不能伪造覆盖。
- 只篡改输出以及篡改输出后同时更改 SHA 元数据，都不能绕过本次真实 stdout 的绑定；无真实完成 run、缺行 stdout 和输出截断不能计覆盖。
- 真实 UART/SPI 未知数据产生的 X 输出使完整帧保持未知；真实功能失败但进程正常完成时，已观察场景可以统计。
- 三种反馈策略实际执行同样的 UART 场景：第二轮观察 45 周期、仅 8 项原有端点断言，两轮累计执行 49 周期；首次 prompt 相同，完整证据保留，API state 不含完整样本数组。
- 外部 typed observer 与轨迹导出回归。

这些测试证明采样和消融实现符合定义，不证明 Agent 提高检出率；有用性需要新的重复对照评测。历史 API 检出率、外部缺陷统计、机器验收和真人记录均未在此文档改写。

## 仍有边界

当前没有通用协议推断、语句插桩或任意外部模块覆盖。沿前状态的推导限于已审计内置寄存输出契约。覆盖缺口可能来自短预算、重置、错误 RTL 或未发生场景，不能由模型自行决定原因。执行日志上限必须足以容纳实际采样；一旦截断，覆盖按未知处理，不能删掉不完整样本后称为完整执行。旧 packet 未保存执行期 SHA 时，现版按未知处理，应重新执行；历史原件及原判定不追溯改写。此处的 hash 与 stdout 一致性用于约束可信本地执行链，不声称可以抵抗操作者同时伪造完整进程结果及所有原件。
