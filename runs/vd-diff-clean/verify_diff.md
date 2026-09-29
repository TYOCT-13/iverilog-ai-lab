# 行为对比：mod10_counter

- **两侧不同**（`different`，退出码 1）
- 基线：`E:\FPGA_WORK\iverilog-ai-lab\rtl\mod10_counter.v`
- 候选：`E:\FPGA_WORK\iverilog-ai-lab\rtl\mod10_counter_bug_wrap9.v`

## 凭什么这么说

| 项 | 值 |
|---|---|
| 测试计划来源 | 离线确定性规划器生成 |
| 期望值证据等级 | reference_model |
| 合约来源 | 从基线 RTL 自动提取的**草稿** |
| 两侧可比的检查项 | 29 |
| 逐拍波形是否比对 | 是 |

裁决只来自两次真实 Icarus 仿真：同一份测试计划、同一份合约，任何一个检查项或任何一个 DUT 可观测信号不同，就是行为差异。

## 差异清单

| 类型 | 位置 | 基线 | 候选 | 说明 |
|---|---|---|---|---|
| record | debug_11 / count | 1001 | 0000 | debug_11 的 count：候选 失败（actual=0000），基线 通过（actual=1001） |
| record | debug_12 / count | 1001 | 0000 | debug_12 的 count：候选 失败（actual=0000），基线 通过（actual=1001） |
| record | debug_13 / count | 0000 | 0001 | debug_13 的 count：候选 失败（actual=0001），基线 通过（actual=0000） |
| record | debug_14 / count | 0001 | 0010 | debug_14 的 count：候选 失败（actual=0010），基线 通过（actual=0001） |
| record | debug_15 / count | 0010 | 0011 | debug_15 的 count：候选 失败（actual=0011），基线 通过（actual=0010） |
| record | debug_16 / count | 0010 | 0011 | debug_16 的 count：候选 失败（actual=0011），基线 通过（actual=0010） |
| record | debug_17 / count | 0011 | 0100 | debug_17 的 count：候选 失败（actual=0100），基线 通过（actual=0011） |
| record | debug_18 / count | 0100 | 0101 | debug_18 的 count：候选 失败（actual=0101），基线 通过（actual=0100） |
| record | debug_19 / count | 0101 | 0110 | debug_19 的 count：候选 失败（actual=0110），基线 通过（actual=0101） |
| record | debug_20 / count | 0101 | 0110 | debug_20 的 count：候选 失败（actual=0110），基线 通过（actual=0101） |
| record | debug_21 / count | 0110 | 0111 | debug_21 的 count：候选 失败（actual=0111），基线 通过（actual=0110） |
| record | debug_22 / count | 0111 | 1000 | debug_22 的 count：候选 失败（actual=1000），基线 通过（actual=0111） |
| record | debug_23 / count | 1000 | 0000 | debug_23 的 count：候选 失败（actual=0000），基线 通过（actual=1000） |
| record | debug_24 / count | 1000 | 0000 | debug_24 的 count：候选 失败（actual=0000），基线 通过（actual=1000） |
| record | debug_edge_01 / count | 1001 | 0001 | debug_edge_01 的 count：候选 失败（actual=0001），基线 通过（actual=1001） |
| record | debug_edge_03 / count | 1001 | 0000 | debug_edge_03 的 count：候选 失败（actual=0000），基线 通过（actual=1001） |
| record | debug_edge_04 / count | 0001 | 0010 | debug_edge_04 的 count：候选 失败（actual=0010），基线 通过（actual=0001） |
| waveform_difference | t=?ns / tb_mod10_counter.dut_i.count | None | None | 同一时刻两侧可观测值不同 |

## 这次没覆盖到什么

- **合约是从基线 RTL 自动提取的草稿**：端口与位宽来自 `module` 头，通常可信；复位极性、同步/异步是猜的。两侧跑在同一套草稿测试台下，因此「两侧不同」仍然可信，而「两侧一致」的覆盖范围可能因此变窄——要提高置信度请用 `--contract` 提供确认过的合约。
- 合约草稿提示：时钟 clk（posedge）来自 always 敏感列表；周期 10ns 是默认值，请按需确认
- 合约草稿提示：复位 rst_n：always 敏感列表含 negedge rst_n（极性/同步性由代码结构推导，请确认）

结论来自两次真实 Icarus 仿真：任何检查项结果不同即为行为差异；波形差异只描述可观测行为，是否构成缺陷仍由规格与人工判断。

