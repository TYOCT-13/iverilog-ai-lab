# 开源规则来源与提炼说明

本文件记录规则包参考的公开开源资料，以及转化为本项目约束的结论。只提炼工程规则，不复制第三方 RTL 实现。

## 公开来源

1. lowRISC Verilog Coding Style Guide：
   https://github.com/lowRISC/style-guides/blob/master/VerilogCodingStyle.md
2. verilog-axi（Alex Forencich）：
   https://github.com/alexforencich/verilog-axi
3. verilog-ethernet（Alex Forencich）：
   https://github.com/alexforencich/verilog-ethernet
4. cocotb：
   https://github.com/cocotb/cocotb
5. LiteX：
   https://github.com/enjoy-digital/litex
6. ZipCPU wb2axip：
   https://github.com/ZipCPU/wb2axip
7. Project F FPGA：
   https://github.com/projf/projf-explore

## 归纳出的共性规则

### 时钟与复位

- 时钟命名应清晰并体现时钟域；多时钟设计不能把跨域信号当普通同步信号使用。
- 复位极性、同步/异步属性必须在 contract 中明确。
- 异步复位释放应经过同步处理；复位分支必须初始化所有状态输出。

### 时序与组合逻辑

- 时序逻辑使用非阻塞赋值，组合逻辑使用阻塞赋值。
- 组合逻辑提供完整默认赋值和 `default` 分支，避免锁存器和非法状态悬挂。
- 综合 RTL 不使用 `#delay`；延时只应存在于 testbench。
- 参数化宽度、计数边界和无效编码必须显式验证。

### 握手、FIFO 和流接口

- Valid/ready 只有在两者同时有效时才发生传输。
- 下游 backpressure 时，valid 和 data 必须保持稳定。
- FIFO 必须验证空、满、读写同时发生、顺序和边界计数。
- AXI/流接口的各通道握手不能依赖对端恰好及时响应。

### CDC 和存储器

- 单比特 CDC 使用同步器，多比特 CDC 使用异步 FIFO、握手或 Gray code 方案。
- 同步器寄存器应具备可识别标记；跨域路径要单独检查。
- RAM/BRAM 读写模式、冲突行为和初始化方式必须写入规格。

### 验证与开源工程

- 仿真、形式验证、综合和硬件验证必须分开报告。
- 测试台应输出结构化结果，并保留失败时的输入、周期和输出。
- 每个实验需固定工具版本、参数、随机种子和原始工件。
- README 应提供目录说明、安装、运行、结果和已知限制。

## 在 Icarus 智测中的落地

- `verification_rules/common.md` 和案例专用规则吸收以上通用规则。
- 规则作为模型上下文，同时通过 contract、Schema、结构化断言和 Icarus 进行强制校验。
- 每次实验保存规则文件 SHA-256 和规则集指纹。
- 第三方项目只作为规则来源，不把其代码、权重或许可证声明复制到本项目。

