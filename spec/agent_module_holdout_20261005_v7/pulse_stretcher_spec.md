# pulse_stretcher — 可重触发脉冲展宽 / Retriggerable pulse stretching

参数 `WIDTH` 默认 **4**，本任务固定使用该默认值。`clk`、`rst_n`、`pulse_in` 为 1 位输入，`pulse_out` 为 1 位寄存输出。时钟周期为 10 ns，在上升沿采样；`rst_n` 异步低有效，自动复位持续两个时钟周期。

复位断言后，输出和展宽状态都清零，无需等时钟。释放复位后，**每个采到 `pulse_in=1` 的上升沿都会立即令边沿后的输出为 1，并重新开始一个 WIDTH 拍窗口**；当前输出已经为 1 时也如此。窗口包含这次触发拍。后续没有新触发时，输出维持到该窗口末拍，下一拍回到 0。低输入不取消尚未结束的窗口。

默认 WIDTH=4 的完整边界：在 `E0` 输入为 1，`E1` 之后输入持续为 0，则 `E0, E1, E2, E3` 边沿后输出均为 1，`E4` 边沿后为 0。若窗口中 `E2` 又采到 1，则以 E2 重开窗口，`E2, E3, E4, E5` 均为 1，后续无触发时 `E6` 回到 0。输入连续多拍为 1 时，每拍都刷新窗口；最后一个高输入采样拍之后还有 **WIDTH-1=3** 个高输出拍，再回落。已空闲时输入保持 0 则输出一直为 0。

复位优先于触发，包括正在展宽时或复位期间输入保持为 1。释放复位后的高输入重新触发一个完整窗口。输出在时钟之间保持最近采样值，异步复位除外。尚未断言复位时的上电输出不作保证；本任务不验证其他参数配置。

**执行约束**：每任务所有实际 episode 共用 **16 个累计刺激周期**；每次提案 / 每个 episode 计划最多 **12 个向量**，累计接受向量上限为 **64**。三个可用请求轮次共享这些额度，不是每轮重新获得 16 拍。`single` 组如只有一次请求，以状态为准；其他组是否继续也服从剩余请求与轮数。每个 episode 独立自动复位，前次计划不会重放，前次电路状态也不会延续。自动初始复位不计刺激；提案中主动加入的复位向量计入刺激周期。

向量 `cycles` 为正整数，提案周期合计不得超过 `max_new_cycles` / 剩余累计周期；向量数不得超过 `max_new_vectors`。同一 episode 内省略的输入保持上次驱动值；初始业务输入默认为 0，复位释放后 `rst_n=1`。使用 `sample_phase=after`，逐拍检查全部输出。不得驱动自动时钟 `clk`；仅使用位宽内的已知数值，不使用 X/Z。

决策顶层严格只有 `action`、`reason`、`vectors`，不添加统计字段、期望输出或可执行内容。操作以空闲、正常触发、完整观察窗口、持续输入及正常重触发为依据，选择能放入当前剩余预算的子集。

**English**: The default WIDTH is 4 and remains fixed for this task. Active-low asynchronous reset clears the registered output and pending window. Every rising edge with `pulse_in=1` asserts the after-edge output and restarts a WIDTH-cycle window, including the triggering edge, even while already active. With one trigger at E0 and no later trigger, E0 through E3 are high and E4 is low. A new trigger at E2 keeps E2 through E5 high and drops at E6 if no further trigger occurs. Held-high input refreshes the window each edge; after its last high sample, three further high-output edges remain. Reset wins. The clock period is 10 ns. Independently reset episodes sample all outputs after each cycle and share 16 total stimulus cycles, with 12 vectors per proposal and 64 accepted vectors total. Up to three request rounds share those caps and obey remaining runtime budgets. Do not drive automatic `clk`, use X/Z, alter parameters, supply expected outputs or add decision fields.
