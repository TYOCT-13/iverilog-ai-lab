# 常用 FPGA 案例

本目录新增 8 类教学/验证案例：

- `sync_fifo.v`：单时钟 FIFO，验证空满标志、写入和读取顺序。
- `uart_tx.v`：UART 发送器，验证起始位、8 位数据、停止位和 busy。
- `spi_master.v`：SPI 主机发送器，验证时钟、MOSI、busy 和 done。
- `handshake_stage.v`：valid/ready 握手级，验证反压和数据保持。
- `debounce.v`：按键去抖，验证连续稳定采样后状态更新。
- `pwm.v`：PWM，占空比输入控制输出高电平比例。
- `mux4.v`：四选一多路选择器，验证所有选择值。
- `sync_reset.v`：异步断言、同步释放复位同步器。

这些实现用于教学和仿真示例，不等价于经过目标 FPGA 厂商时序签核的量产 IP。

## Agent 对照试验的完整规格

新试验读取 `agent_protocols.json` 中的 `spec_path` 与 `cycle_budget`，而非把上述一句话简介当作完整协议。预算是多轮累计激励周期上限，不含测试台的自动初始复位，也不是历史试验预算的追溯改写。

| 案例 | 规格 | 已验证参数 | 累计周期上限 |
| --- | --- | --- | ---: |
| sync_fifo | [完整规格](sync_fifo_spec.md) | DATA_WIDTH=8、DEPTH=4 | 160 |
| uart_tx | [完整规格](uart_tx_spec.md) | CLKS_PER_BIT=4 | 512 |
| spi_master | [完整规格](spi_master_spec.md) | WIDTH=8 | 384 |
| handshake_stage | [完整规格](handshake_stage_spec.md) | WIDTH=8 | 160 |

规格面向仓库中实际 RTL 与已经逐拍对齐的参考模型。本轮已修复 FIFO 同拍读写计数问题，旧实验保持原记录；SPI 的边沿后 MOSI 更新与通用 IP 的常见约定有差别，详见规格。通过本项目判据不代表符合所有通用协议或完成硬件签核。
