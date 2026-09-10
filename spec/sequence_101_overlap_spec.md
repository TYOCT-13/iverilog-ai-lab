# sequence_101_overlap 规格

`clk` 上升沿采样 `bit_in`，`rst_n` 为低有效异步复位。每当最近三个采样位为 `101`，`detected` 在该沿之后为一个周期的 1；历史窗口逐位滑动，因此 `10101` 在第 3、5 个采样沿均命中。

时序图源：`waveforms/sequence_101_overlap_basic.json5`。
