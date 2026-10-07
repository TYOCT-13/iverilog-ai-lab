# event_accumulator 模块规范

> RTL: `targets/event_accumulator/B/event_accumulator.v`

## 1. 模块目的

未提供模块目的。

## 2. 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| — | — | 本模块没有可配置参数。 |

## 3. 时钟与复位

- 时钟：`{"signal": "i_clk", "period_ns": 10, "edge": "posedge"}`
- 复位：`{"signal": "i_rstn", "active_level": 0, "synchronous": false, "assert_cycles": 2}`

## 4. 接口信号规范

| 信号 | 方向 | 位宽 | 时钟域 | 语义角色 | 描述 |
| --- | --- | --- | --- | --- | --- |
| `i_clk` | input | 1 | 未声明 | clock | i_clk |
| `i_rstn` | input | 1 | 未声明 | reset | i_rstn |
| `i_enable` | input | 1 | 未声明 | input_data_or_control | i_enable |
| `i_event` | input | 1 | 未声明 | input_data_or_control | i_event |
| `i_clear` | input | 1 | 未声明 | input_data_or_control | i_clear |
| `o_count` | output | 4 | 未声明 | output_data_or_control | o_count |

## 5. 周期行为与延迟

- B 原 RTL 的故意错误实现的等语义样式候选；此文档描述实际错误行为，不代表正确功能合同。
- 异步 i_rstn=0 立即归零；同步 i_clear=1 优先清除；否则 i_event=1 即计数，不检查 i_enable。i_enable=0 且 i_event=1 时也会加一，这是必须保留的原故意错误。
- 接受事件按模十六累加；未置位事件时保持。相对于 A，E2 的禁止许可事件仍被计入。

## 6. WaveDrom 时序图

### B 原错误时序

描述 B 原变体及等语义候选的实际逐拍行为；B/C 与 A 的区别是原故意错误，需要在维护中保留。

![B 原错误时序](waveforms/event_accumulator_variant-behavior.svg)

- WaveJSON：[event_accumulator_variant-behavior.json5](waveforms/event_accumulator_variant-behavior.json5)

## 7. 边界、反压与错误

- 异步复位，清除与事件同时出现，许可关闭，计数从 15 回绕到 0。
- i_clear 为 X/Z 且许可和事件为 1 时沿后仍加一；enable/event 未知时原条件不为真。

## 8. CDC 与综合约束

- 固定公开接口、时钟边沿、复位极性及原有寄存器初始化值；不新增状态或可见流水延迟。
- 仅嵌套 plain case，显式匹配已知 1，其余值进入 default，保持原 if 对 X/Z 条件的非真分支语义。清除 X/Z 时仍继续检查后续有效事件或有效数据。
- 四态输入只用于此次候选的差分维护验证；公开正确行为合同的合法输入仍为已知、合法位宽数据。
- 此图是明确声明的行为时序，输出为对应上升沿 after 值；不是实测仿真轨迹。B/C 文件必须保留与正确 A 不同的原语义。

## 9. 验证与验收

- 六个原变体与其候选逐一进行同刺激、全部真实输出差分；记录编译和执行退出码、stdout/stderr。
- A 使用项目原公开逐拍语义判据通过；B/C 在公开判据仍呈现各原故意错误，而且双侧观察与失败位置完全一致。

## 10. 可追溯性

- 规格模块：`event_accumulator`
- RTL 路径：`targets/event_accumulator/B/event_accumulator.v`
- 交付要求：本文档、WaveJSON 和 SVG 必须与同一版本规格一同发布。
