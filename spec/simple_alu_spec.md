# simple_alu 规格

组合四运算 ALU。`op=0` 加法、`1` 减法、`2` AND、`3` OR、`4` XOR、`5` 左移一位、`6` 右移一位；加法 `carry` 为第 9 位，减法 `carry` 表示 `a>=b`，其他操作为 0。`zero` 在结果为零时为 1。

时序图源：`waveforms/simple_alu_basic.json5`。
