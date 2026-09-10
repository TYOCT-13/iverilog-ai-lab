# 演示证据包指南

方向 E 的目标是让一次网页演示可以脱离页面会话复核。

## 生成方式

网页完成 AI 流水线后，点击“生成本次运行证据包”。也可以运行：

```powershell
 python scripts\create_evidence_pack.py `
  --result .iverilog-ai\pipeline-ui\pipeline_result.json `
  --output-dir .iverilog-ai\pipeline-ui\evidence-pack
```

命令默认同时生成同级 ZIP：`evidence-pack.zip`，网页按钮“下载证据包 ZIP”也会提供相同文件。若只需要目录而不需要压缩包，可追加 `--no-zip`。

## 文件内容

- `pipeline_result.json`：计划、contract、覆盖率和仿真结果。
- `result.json`：Icarus/vvp 原始结构化执行结果。
- `testplan.json`：模型生成并校验后的计划。
- `dut_contract.json`：DUT 端口、时钟和复位合约。
- `tb_*.v`：受控生成的 testbench。
- `report.md`：人类可读报告（存在时）。
- `waveform.vcd`：波形证据（存在时）。
- `evidence_manifest.json`：文件大小、SHA-256、运行 ID 和状态。
- `README.md`：证据包索引与复核步骤。

## 建议提交两套证据

1. 正确 RTL 通过案例：展示合法计划、完整记录和无失败反例。
2. 缺陷 RTL 检出案例：展示失败指纹、反例、VCD 和候选修复前后对比。

证据包不得保存 API Key。Icarus 仿真结果不能代替综合、时序或上板证据。
