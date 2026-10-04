# 内置参考判据误报诊断（2026-10-04）

范围：`.iverilog-ai/agent-comparison-live-chat-v2/` 的 SPI/FIFO `reference_false_alarm`。执行者为外部适配器实现代理，本次只读检查已有计划、生成测试台、仿真失败记录与 VCD；**不是人工独立复核**。未发起 API、未修改冻结源码、未改写 60 行 pilot 原始结果。

## 结论

确认是内置参考模型与 `sample_phase="before"` 的真实测试台时序不一致。`reference_expectations()` 遍历向量后无条件调用 `state.step(inputs, cycles)`，从未读取 sample_phase。测试台 before 分支则先 `#1`、执行观测/断言，再等待该次时钟沿；多周期向量仅最后一周期断言，所以断言时通常只经过 `cycles-1` 个本向量时钟沿。

这不是 API 猜错 expected：API 向量 expected 为空，错误数字由内置参考模型生成并写入 authoritative_plan.json。baseline 的这些失败不能称为被测设计缺陷。现有 reference-audit 把结果标成 reference_false_alarm，而非 detected，是必要的防误计数措施。

## 已有证据定位

| sample | 案例 / 策略 | 基线 audit 失败 | 对应时序 |
|---|---|---|---|
| 007 | sync_fifo / single，候选为 full_off_by_one | cycle 5，full expected=1 actual=0 | 连续 4 写 before 的最后采样在 67 ns，此时 count=3；75 ns 第 4 写后 full 才变 1 |
| 032 | spi_master reference / single | cycle 2 busy 1→0；cycle 3 sclk 1→0 | start 在 36 ns 置 1，37 ns before 时 busy 仍 0；45 ns 沿后 busy 才 1。47 ns before 时 sclk 仍 0，55 ns 才变 1 |
| 033 | spi_master reference / feedback | 与 032 相同两项 | 启动片段相同，后续等待为 24 周期而非 20，不影响先前错误 |
| 042 | spi_master done_missing / single | 基线 7 项：cycle 4 busy、25 mosi/busy、27 sclk、28 sclk、49 mosi/busy | 多次单周期 before 启动以及两周期 before 忙等，均用了推进最后时钟沿后的参考值 |

每项原始证据位于 `sample-NNN/audit-1/`：`testplan.json` 为原始计划、`authoritative_plan.json` 为内置期望、`tb_<module>.v` 为实际断言时序，`pipeline_result.json` 保存 failures 与实际 run_stdout/vcd 路径。

原始计划概况：

- 007：reset low 2 before；release + write 0xAA 4 before；write 0x55 1 before；read 5 before。
- 032/033：reset low 2 after；start(data=0) 1 before；start(data=255) 1 before；start low 等待 20/24 after。
- 042：reset low 2 after；idle 2 before；start(data=0) 1 before；wait 20 after；start(data=255) 1 before；busy wait 2 before；start(data=170) 1 before；wait 20 after；start(data=85) 1 before；wait 10 after。

这些计划均显式给出了相关输入，因此本次四行误报不需要用“缺省输入”假说解释。FIFO/SPI RTL 的 reset 都是异步低有效；当前失败点 reset 已解除，根因不是 reset 极性或未释放，而是启动/写入最后一沿尚未发生。

007 尤其危险：错误参考值可能恰好符合 full 提前拉高的已有变体，使候选看似通过、正确基线反而失败。因此不能只排除“API 质量差”的单行，更不能把这些结果拿来证明更高检出率。

## 原始证据指纹

| sample | audit testplan SHA256 | audit VCD SHA256 |
|---|---|---|
| 007 | fb6d986a46f7ef40f43718e98983b406a8d5472f4c23ea9a878d6bd7717ab425 | 450fa14a7553adb5faf9db03911a4abf8f163edd9a2885bb2788ee924aae2898 |
| 032 | b8b5795cf18e86d0b612cb0315df4bf42dc73e3fc33852860e73c99362cf5c73 | 763b3f440121a13b5f6f02c8159662c64c5a50ce035f304e5fc1d515272b6d3e |
| 033 | 7ba2753088be14396e9e3e13498d8787e7d00bf8f368410c6a414f35c5e668d3 | 0785cffcab7cb1475ea204d95423053d02d20ba7d0a7d1a6cb471d128859d095 |
| 042 | f91a292cf8ac5a0edd3802bd1b9c2d127e8542ddc3b75b72114915f762840045 | f9bf4a69280f581db7af89683e9a104224fd8297c81a917b83bdf939165ff111 |

## 建议的最小安全修正（本诊断未实施）

短期可先 fail-closed：时序模块计划含 before 时，不将现有模型作为权威 oracle，显式返回 unsupported_sampling/inconclusive。不能静默把 before 改成 after，也不能把 unsupported 当 passed。组合逻辑无时钟的 before/after 处理另论。

完整修正应明确区分三件事：应用本周期输入/异步复位、读取当前可见输出、时钟推进。after 先推进再读取；before 在最后一周期推进前读取，随后仍推进该时钟沿以保持下一个向量的状态正确。不能只把 cycles 改成 cycles-1 而漏掉最后一次状态推进，也不能通用地 step(inputs,0) 冒充异步复位，因为现有各模型的 reset 只在循环体内处理。

另有相邻风险：`completed_inputs` 每个向量重新补默认值，而测试台未赋值的输入保持上次值。虽然不是这四行的根因，若修 reference 输入语义，需从 contract 的端口初值/复位后状态初始化并跨向量持久更新，不能每次默认 rst_n=1 或 start=0。不得为兼容不支持输入而伪造已验证期望。

## 有意义的回归与重评

1. 固定保存上述四份原始计划，用正确 baseline 真实 Icarus 重放，修复/门控后不能再出现权威假失败；产物另开目录，不改旧记录。
2. SPI 单拍 before start、连续 before、before→after 与 after→before 混合；确认采样输出和向量结束后的模型状态都对齐。
3. FIFO 4 次 before 写：最后 before full 应为 0，随后时钟沿 full 才为 1；紧接的向量必须继承已完成第 4 写的状态。
4. 异步 reset 在非时钟沿 before 拉低，输出应立即复位；同步 reset 的 before 则保留旧输出，下一沿才复位。
5. 稀疏输入：start/rst_n/wr_en 在下一向量省略时必须保持，与真实测试台一致。
6. 已有全 after/full-input 回归仍应通过；同时保留已有错误 RTL 的有效缺陷检出，避免“删掉断言修好误报”。
7. 如果采用修正后的判据重算历史 pilot，只能称为固定历史 API 计划的离线重评，必须与原 live 60 行独立保存；不能声称原模型请求本来就获得这些新结果。
