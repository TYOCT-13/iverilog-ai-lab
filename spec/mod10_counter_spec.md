# mod10_counter 规格

`clk` 为上升沿时钟；`rst_n` 为低有效异步复位，复位时 `count=0`。释放复位后，`enable=1` 时每个上升沿计数，9的下一值为0；`enable=0` 时保持不变。`count` 仅允许0到9。验证覆盖复位、暂停、连续计数和回绕。

时序图源：`waveforms/mod10_counter_basic.json5`。
