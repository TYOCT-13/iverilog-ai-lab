# 单时钟 FIFO 规则

- 写入仅在 `wr_en=1` 且 `full=0` 时发生。
- 读取仅在 `rd_en=1` 且 `empty=0` 时发生。
- 数据必须先进先出；空 FIFO 不能产生有效读数据。
- FIFO 达到容量后 `full=1`，空状态为 `empty=1`。
- 若存在读写同时发生，必须明确计数更新和读数据时序，禁止出现 underflow/overflow。
- 跨时钟 FIFO 不能直接同步多位二进制指针，应使用 Gray code 或异步握手。
