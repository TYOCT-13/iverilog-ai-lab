# handshake_stage：本实现的验证规格

规格版本：2026-10-04 / agent-protocols-v1。依据 `rtl/handshake_stage.v`、`examples/handshake_stage_contract.json` 与 `src/iverilog_ai/core/reference_model.py`。模块是一项容量的弹性寄存级，数据宽度固定验证为 WIDTH=8。

## 接口与复位

- `clk` 10 ns，上升沿有效；`rst_n=0` 异步断言复位，之后 `out_valid=0, out_data=0`。因组合表达式，复位后空级的 in_ready 为 1。
- 输入 `in_valid`、`out_ready` 为 1 位，`in_data` 为 8 位；输出 `in_ready`、`out_valid` 为 1 位，`out_data` 为 8 位。
- 默认输入 `rst_n=1, in_valid=0, in_data=0, out_ready=0`。释放复位与输入驱动避开有效边沿；未列出输入沿用上一向量。
- `in_ready = !out_valid || out_ready`，为组合输出，out_ready 变化可立即使 in_ready 变化。

## 握手和保持

1. 输入接受依据上升沿之前的 `in_valid && in_ready`。空级即使下游 out_ready=0，仍可接受一个数据项；在该边沿后 out_valid=1、out_data=输入数据。
2. 下游消费依据边沿之前的 `out_valid && out_ready`，不是以边沿后的 out_valid 去判断同一拍是否消费。
3. out_valid=1 且 out_ready=0 时进入反压，in_ready=0；out_valid 和 out_data 必须保持。此期间 in_data 变化不能覆盖已缓存的数据。
4. out_ready=1 时 in_ready=1：已有项可在同一边沿被消费，新项也可被接受，out_data 替换为新数据，out_valid 保持为 1。可实现每周期一个数据项的连续传递。
5. in_ready=1 且 in_valid=0 的边沿后 out_valid=0，但 out_data 保持上次数据；无效数据不是强制清零。
6. 空级无输入时保持无效，不因 in_data 变化而捕获内容。复位会丢弃未消费的缓存项，下一项需在释放后重新请求。

## 激励约束与采样

合法的 upstream producer 在 in_valid=1 而 in_ready=0 时应保持 in_valid 与 in_data，直至被接受。若专门改变被阻塞的输入以验证寄存级不会意外覆盖输出，需明确标为健壮性探针；不要宣称该输入序列符合完整的 upstream 协议。

逐拍输出期望使用 `sample_phase=after`。由于 in_ready 是组合量，该边沿后的 in_ready 是针对下一次接受条件的值，不能将它误读为该边沿之前的 ready。

## 场景与执行预算

- 空级接收、无 valid 时保持、反压多周期保持、释放反压后消费。
- 消费而不补入、同拍消费并补入、连续满速流、全 0/全 1 及非对称数据。
- 缓存占用时复位、复位后恢复、背压输入稳定与显式健壮性探针。
- 本轮多轮共享累计激励预算 **160 周期**。每个策略使用相同累计上限；实际场景覆盖由执行器观察，不由 Agent 自称已覆盖。
- PASS/FAIL 使用已逐拍对齐的参考模型，Agent 自写 expected 不影响最终判据。
