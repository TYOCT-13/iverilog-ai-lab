# Shared short-budget verification study

The cumulative stimulus limit for this task is 48 cycles across all executed episodes. The executor controls the remaining cycle, request and round budgets through execution state. Obey max_new_cycles, remaining_stimulus_cycles, remaining_rounds, max_new_vectors and any stated request cap. Do not invent additional requests or treat the cumulative cap as a fresh allowance in every episode.

Each permitted episode is independent: the contract automatically resets a fresh DUT before it; earlier vectors, input levels and circuit state are not continued or replayed. The automatic initial reset is outside stimulus accounting; any manually proposed reset vectors count toward the cumulative cap. Within an episode, omitted inputs hold their last driven levels. Use sample_phase=after and known binary input values; the executor checks each held-input cycle after its edge. Never drive the automatically generated clock.

The scenario lists below describe the wider regression scope. Choose a focused subset that fits the remaining cumulative budget; they do not require every scenario in one episode or all scenarios in this task. Compute the sum of proposed vector cycles privately and keep it within max_new_cycles. Further proposals or a stop remain subject to the executor's current request and round limits.

The decision JSON has exactly the existing top-level action, reason and vectors fields. Do not add vector_count, total_cycles, cycle_sum or other statistics at the top level. Each vector retains its cycles field and the existing decision schema. Do not supply expected outputs, executable content, new oracle rules or fabricated coverage claims; the executor owns the reference model and observed evidence.

Protocol-operation priority for this case: Prioritize an actual accepted transmission and observation of a complete frame through busy release, using the original E0 through E40 timing when the remaining budget can contain it. Idle-only or reset-only observations do not establish transmitted-frame behavior. Choose your own legal data and bounded additional protocol probes.

Study disclosure: the short-budget scope, episode/sampling reminders and generic protocol priorities form a combined prompt optimization reused across all API groups for this case. This development-set comparison does not identify a single-factor causal effect or establish held-out generalization.

The original interface, acceptance rules and detailed timing below remain unchanged.

# uart_tx：本实现的验证规格

规格版本：2026-10-04 / agent-protocols-v1。依据 `rtl/uart_tx.v`、`examples/uart_tx_contract.json` 与 `src/iverilog_ai/core/reference_model.py`。此处是仓库教学发送器；外部 AXI-Stream UART 的 `prescale` 接口属于另一份规格，不能混用。

## 接口、参数与复位

- 固定验证参数 `CLKS_PER_BIT=4`；输入数据 8 位，无奇偶校验，发送 1 个起始位、8 个 LSB 优先数据位、1 个停止位，即 8N1。
- `clk` 周期 10 ns，上升沿有效；`rst_n=0` 异步断言复位。复位立即清除正在发送的状态，`tx=1`、`busy=0`。释放复位避开采样边沿。
- 输入 `start` 为 1 位，`data_in` 为 8 位；输出 `tx`、`busy` 为 1 位。默认输入 `rst_n=1, start=0, data_in=0`。
- 所有明确数拍的输出检查使用 `sample_phase=after`，输入必须先于有效边沿稳定。未指定的输入沿用上一向量；发送后明确把 `start` 拉低。

## 接受与串行时序

令 E0 为空闲（边沿前 `busy=0`）且 `start=1` 的上升沿：

1. E0 接受当时 `data_in`，锁存整帧；E0 后 `busy=1, tx=0`。数据在忙期间发生变化不会改写已锁存的帧。
2. 起始位为 0，区间 E0 至 E3 共 4 个周期。数据位 0 从 E4 开始，之后每 4 个周期切换到下一位，顺序为 data[0] 至 data[7]。数据位 7 从 E32 开始。
3. E36 至 E39 的停止位为 1，`busy` 仍为 1。E40 后 `busy=0, tx=1`。从接受到释放忙状态恰好需要 `10 * CLKS_PER_BIT = 40` 个后续上升沿。
4. 起始位、每个数据位及停止位均保持 `CLKS_PER_BIT` 个周期；不能只在 E40 末拍检查，因为末拍没有串行位序信息。
5. 边沿前 `busy=1` 时的 `start=1` 被忽略，包括 E40（结束边沿）；本模块没有待发队列。需要下一帧时，在 E41 或更晚的空闲边沿重新提供 start。
6. `start` 若持续为 1，第一次发送结束后的下一空闲边沿会再次接受数据；它不是只对上升沿触发。因此通常用一个周期 start 脉冲来发送一帧。

## 异常和边界场景

- 无 start 时保持空闲高电平。
- 非位序回文的数据，如 0x96、0x3A，用于观察 LSB 顺序；0x00、0xFF 及交替位用于检查完整位持续时间。
- 忙期间再次请求、忙期间改变 data_in、结束前后请求、两帧及多帧发送。
- 帧中复位：正在发送的帧中止，输出回到空闲；释放后新的请求仍可发送完整帧。
- 本模块没有接收器、校验位、可变字长、FIFO 或 AXI valid/ready；不要生成不存在的信号。

## 执行预算与判据


参考模型按实际参数逐拍生成 tx/busy 期望，覆盖期望不以 Agent 自写数值为准。周期预算、实际执行周期、向量数、输出采样数和完整帧覆盖分别报告；增加预算本身不代表 AI 有效性改善。
