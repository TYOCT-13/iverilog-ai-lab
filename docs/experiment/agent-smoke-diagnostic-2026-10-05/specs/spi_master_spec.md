# Short-budget first-proposal scope: 20 stimulus cycles

This episode has at most 20 stimulus cycles and one API proposal. The scenario lists below describe the full regression scope; choose a focused SUBSET that fits this episode. They are not a requirement to run every scenario. Do not plan multiple complete frames if they do not fit.

The contract automatically resets the DUT before the episode; those initial reset cycles are outside stimulus accounting. Any manual reset vectors count toward the stimulus budget. Every held-input cycle is checked after its edge. Compute the sum of vector cycles privately and keep it at or below max_new_cycles.

The decision JSON has ONLY the existing top-level action, reason, vectors fields. Do not add summary fields such as vector_count, total_cycles, cycle_sum, cycles_total or cycles at the top level. Each vector keeps its required cycles field. Use the existing schema; no new format or executable content.

The following circuit interface, acceptance rules and timing remain unchanged.

# spi_master：本实现的验证规格

规格版本：2026-10-04 / agent-protocols-v1。依据 `rtl/spi_master.v`、`examples/spi_master_contract.json` 与 `src/iverilog_ai/core/reference_model.py`。这是最小发送与波形示例，不提供 CS、MISO、可配置 CPOL/CPHA 或接收能力；不宣称完整标准 SPI 主机。

## 接口、参数与复位

- 本轮固定验证 `WIDTH=8`。RTL bit counter 为 4 位，参考模型的数据掩码为 8 位；本轮不外推其他位宽的正确性。
- `clk` 10 ns，上升沿有效；`rst_n=0` 异步断言复位。复位后 `sclk=0, mosi=0, busy=0, done=0`。释放复位避开采样边沿。
- 输入 `start` 为 1 位，`data_in` 为 8 位；输出 `sclk`、`mosi`、`busy`、`done` 均为 1 位。默认输入 `rst_n=1, start=0, data_in=0`。
- 向量输入在边沿前稳定，保持指定 cycles；未列出输入沿用上一向量。数拍检查使用 `sample_phase=after`。

## 启动与边沿语义

令 E0 为边沿前 `busy=0` 且 `start=1` 的上升沿：

1. E0 后 `busy=1, sclk=0, mosi=data_in[7], done=0`，数据被锁存。忙期间改变 data_in 或再次请求 start 不改写当前发送。
2. 从 E1 起，每个 busy 的 clk 上升沿翻转 sclk。E1、E3、…、E15 为 sclk 低→高，E2、E4、…、E14 为高→低。
3. RTL 在 sclk 低→高的同一个 clk 上升沿后推进移位，因此 E1 后 mosi 已变成锁存数据的 bit6，E3 后变 bit5，依次到 E13 后 bit0；这些值在中间的 sclk 高→低边沿保持。
4. 在 E15 最后一次 sclk 低→高后，`busy=0, done=1, sclk=1`，mosi 保持 bit0。E16 空闲边沿使 `sclk=0, done=0`，mosi 保持旧值。完成脉冲恰好为一个 clk 周期。
5. 对 WIDTH=8，从 E0 接受到 E15 完成需要 `2 * WIDTH - 1 = 15` 个后续上升沿；另需一个空闲边沿恢复 sclk 低电平。完整的接受、完成和 idle 恢复至少覆盖 17 个采样边沿 E0…E16。
6. start 持续为 1 时，完成后的第一个空闲边沿可接受新帧；没有请求队列。通常用一周期脉冲发起一次发送。

## 与标准 SPI 使用方式的区别

在本实现里，E1 后看到的是下一位，不能把边沿后 MOSI 当作“接收器在这个 sclk 上升沿采到的当前位”。用于相邻设备的 SPI 电气时序和同一边沿建立/保持关系尚未验证。项目当前判据验证上述可观测寄存器行为，不能将其通过结果写成标准 CPHA 模式认证。

## 应覆盖的场景与预算

- 起始后的完整 sclk 翻转数、MOSI 位序、完成时 busy 释放、done 单周期以及空闲恢复。
- 非回文数据、全 0/全 1、连续请求、忙期间 start 请求与 data_in 改变。
- 发送中复位、复位后重发、完成脉冲之后的保持状态。
- 期望由已对齐参考模型逐拍提供，Agent 负责规划激励，不能修改判据。
