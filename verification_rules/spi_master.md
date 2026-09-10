# SPI 主机规则

- 空闲 `sclk=0`，`start` 接受后 `busy=1`。
- MOSI 按约定的高位优先顺序发送固定宽度数据。
- 完成一帧后产生 `done`，随后回到空闲。
- CPOL/CPHA、片选时序和位序必须在 contract 或规格中明确，不能由模型猜测。
