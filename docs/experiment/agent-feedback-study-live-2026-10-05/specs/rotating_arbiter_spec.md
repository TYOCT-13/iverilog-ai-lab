# rotating_arbiter — 轮转优先仲裁 / Rotating priority arbiter

无参数。端口为 `clk`、`rst_n`（1 位输入）、`request`（4 位无符号输入）、`advance`（1 位输入）和 `grant`（4 位无符号输出）。时钟为 10 ns 周期的上升沿；`rst_n` 为异步、低有效复位。复位后，`grant=0`，内部优先起点为 0。

每个上升沿按边沿前的优先起点 `p` 检查 `request`，优先级依次为 `p, (p+1)%4, (p+2)%4, (p+3)%4`。选中第一个请求置位的位置 `s`；边沿后的寄存输出 `grant=1<<s`。如果没有请求，输出为 0。`grant` 每拍重新生成，与上拍输出无关；始终为 one-hot 或 0。

如果当拍有选中请求且 `advance=1`，优先起点在边沿后更新为 `(s+1)%4`；否则起点保持。**advance 只改变后续拍优先级，本拍 grant 始终依据边沿前的旧起点。** 无请求时，即使 `advance=1` 也不推进。复位优先于所有业务输入。上电但尚未断言复位时的输出不在本规格范围内。

**正常时序例**（先完成自动复位）：`request/advance` 依次为 `2/1, 4/1, 0/1, 8/0, 8/1`，对应每拍之后的 `grant` 为 `2, 4, 0, 8, 8`，优先起点依次为 2、3、3、3、0。每拍选择都使用旧起点。

```wavedrom
{"signal":[{"name":"clk","wave":"p....."},{"name":"rst_n","wave":"01...."},{"name":"request","wave":"======","data":["0","2","4","0","8","8"]},{"name":"advance","wave":"01..01"},{"name":"grant (after)","wave":"======","data":["0","2","4","0","8","8"]}],"head":{"text":"Old pointer selects this edge; advance affects the next"}}
```

**执行约束**：**每次提案 / 每个 episode 计划最多 12 个向量**；所有实际执行的 episode 合计最多 **16 个刺激周期**。向量 `cycles` 为正整数，本提案周期合计不得超过状态中的剩余累计周期。接受的向量累计 64 个仅是内部安全上限，不是单次提案额度。自动复位过程不属于刺激预算。每个新 episode 都独立自动复位，前一次电路状态不会延续。使用 `sample_phase=after`，每个周期检查全部输出（`reference_sampling=per_cycle`）；不要驱动由执行器自动产生的 `clk`。输入只能使用其位宽内的已知二进制数值。

决策顶层严格只有 `action`、`reason`、`vectors`；不添加统计字段或期望输出。请求数、轮数和剩余周期以运行状态为准。选择操作时以请求选择、保持起点、正常推进、无请求和环回的正常协议行为为依据。

**English**: A parameter-free registered 4-way arbiter resets `grant` and the priority pointer to 0 on asynchronous active-low reset. Each rising edge selects the first requested position in cyclic order from the old pointer. The after-edge grant is one-hot or zero. Only a successful selection with `advance=1` sets the pointer to the selected index plus one modulo four; otherwise the pointer holds. Advance affects subsequent edges, never the current selection. Each proposal / episode plan allows at most **12 vectors**. All executed episodes share a cumulative **16 stimulus cycles**, bounded by the remaining runtime state. Each episode is independently reset. The 64 accepted-vector total is an internal safety ceiling, never a per-proposal allowance. Sample all outputs after every cycle; do not drive automatic `clk`, use X/Z, add expected outputs or extra decision fields.
