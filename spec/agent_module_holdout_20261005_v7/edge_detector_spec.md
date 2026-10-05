# edge_detector — 同步上升沿检测 / Synchronous rising-edge detection

无参数。`clk`、`rst_n`、`signal_in` 为 1 位输入，`rising` 为 1 位寄存输出。`clk` 周期为 10 ns，在上升沿采样；`rst_n` 异步低有效，自动复位持续两个时钟周期。

复位断言后，`rising=0`，采样历史也清为 0，无需等时钟。释放复位后，每个上升沿把当拍 `signal_in` 与前一拍采样值比较：只有前一拍为 0、当拍为 1 时，边沿后的 `rising=1`；其他三种组合输出均为 0。当拍输入成为下一拍的历史。

输入连续为 1 时只在该连续高电平的首个采样拍产生一次脉冲；回到 0 的当拍输出为 0，之后再次采到 1 可重新产生脉冲。每次复位都会清除旧历史：复位释放后首拍输入为 1 时，也按历史 0 处理。输出是寄存值，时钟之间输入变化本身不立即改变输出；这里验证的是同步采样到的变化。尚未断言复位时的上电输出不作保证。

**正常时序**：复位后输入采样为 `0, 1, 1, 0`，边沿后的输出依次为 `0, 1, 0, 0`。

**执行约束**：每任务所有实际 episode 共用 **16 个累计刺激周期**；每次提案 / 每个 episode 计划最多 **12 个向量**，累计接受向量上限为 **64**。三个可用请求轮次共享这些额度，不是每轮重新获得 16 拍。`single` 组如只有一次请求，以状态为准；其他组是否继续也服从剩余请求与轮数。每个 episode 独立自动复位，前次计划不会重放，前次电路状态也不会延续。自动初始复位不计刺激；提案中主动加入的复位向量计入刺激周期。

向量 `cycles` 为正整数，提案周期合计不得超过 `max_new_cycles` / 剩余累计周期；向量数不得超过 `max_new_vectors`。同一 episode 内省略的输入保持上次驱动值；初始业务输入默认为 0，复位释放后 `rst_n=1`。使用 `sample_phase=after`，逐拍检查全部输出。不得驱动自动时钟 `clk`；仅使用位宽内的已知数值，不使用 X/Z。

决策顶层严格只有 `action`、`reason`、`vectors`，不添加统计字段、期望输出或可执行内容。操作以正常采样变化、持续电平、返回低电平及复位恢复为依据，选择能放入当前剩余预算的子集。

**English**: With no parameters, a registered 1-bit output reports sampled rising transitions. Asynchronous active-low reset clears the output and previous sample to zero. At each rising clock edge, the after-edge output is one only for the old/new sampled pair 0/1; then the current input becomes the next history. Held-high input does not repeatedly assert the output. Reset has priority, and a first high sample after reset counts as a rise. The clock period is 10 ns. Each independently reset episode observes all outputs after every cycle. All actual episodes share 16 stimulus cycles, at most 12 vectors per proposal and 64 accepted vectors in total, bounded further by runtime state. Up to three request rounds share these caps; never assume a fresh budget or continued circuit state. Do not drive automatic `clk`, use X/Z, supply expected outputs or add decision fields.
