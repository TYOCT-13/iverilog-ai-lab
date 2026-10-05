# credit_guard — 饱和信用计数 / Saturating credit count

无参数。端口为 `clk`、`rst_n`、`acquire`、`release_req`（均为 1 位输入）和 `credits`（3 位无符号输出）。时钟为 10 ns 周期的上升沿；`rst_n` 为异步、低有效复位。

复位断言后，`credits=3`，无需等待时钟。释放复位后，每个上升沿使用该边沿之前的输入和计数，按下表更新；输出在该边沿之后稳定。

| acquire | release_req | 更新规则 |
|---|---|---|
| 0 | 0 | 保持 |
| 1 | 0 | 大于 0 时减 1；为 0 时保持 0 |
| 0 | 1 | 小于 7 时加 1；为 7 时保持 7 |
| 1 | 1 | 保持 |

优先级：低有效复位优先于所有业务输入。计数始终在 0～7 之间。输入可以连续多拍保持，规则逐拍执行。上电但尚未断言复位时的输出不在本规格范围内。

**正常时序例**（先完成自动复位）：`acquire/release_req` 依次为 `00, 10, 01, 00`，对应每拍之后的 `credits` 为 `3, 2, 3, 3`。

```wavedrom
{"signal":[{"name":"clk","wave":"p...."},{"name":"rst_n","wave":"01..."},{"name":"acquire","wave":"0010."},{"name":"release_req","wave":"00010"},{"name":"credits (after)","wave":"=====","data":["3","3","2","3","3"]}],"head":{"text":"Reset then four active edges"}}
```

**执行约束**：**每次提案 / 每个 episode 计划最多 12 个向量**；所有实际执行的 episode 合计最多 **16 个刺激周期**。向量 `cycles` 为正整数，本提案周期合计不得超过状态中的剩余累计周期。接受的向量累计 64 个仅是内部安全上限，不是单次提案额度。自动复位过程不属于刺激预算。每个新 episode 都独立自动复位，前一次电路状态不会延续。使用 `sample_phase=after`，每个周期检查全部输出（`reference_sampling=per_cycle`）；不要驱动由执行器自动产生的 `clk`。输入只能使用其位宽内的已知二进制数值。

决策顶层严格只有 `action`、`reason`、`vectors`；不添加统计字段或期望输出。请求数、轮数和剩余周期以运行状态为准。选择操作时以信用消耗、归还、保持、上下界的正常协议行为为依据。

**English**: A parameter-free 3-bit credit counter resets asynchronously to 3 on active-low `rst_n`. At each rising edge, acquire alone decrements with saturation at 0, release_req alone increments with saturation at 7, and both/neither hold. Reset wins. Observe the registered output after every edge. Each proposal / episode plan allows at most **12 vectors**. All executed episodes share a cumulative **16 stimulus cycles**, bounded by the remaining runtime state. Every episode starts from a fresh automatic reset. The 64 accepted-vector total is an internal safety ceiling, never a per-proposal allowance. Do not drive automatic `clk`, use unknown X/Z values, add output expectations or extra decision fields.
