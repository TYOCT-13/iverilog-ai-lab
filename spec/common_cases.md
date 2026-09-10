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
