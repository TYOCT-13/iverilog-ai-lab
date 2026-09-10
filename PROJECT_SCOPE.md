# Icarus 智测项目范围

本项目是围绕 Icarus Verilog 开源生态构建的非官方 AI 辅助验证扩展。

## 第一阶段目标

- 跑通计数器与交通灯两个可信 RTL 案例。
- 使用 Icarus Verilog 和 vvp 完成真实编译与仿真。
- 用结构化 JSON 描述测试计划，AI 输出必须先经过校验。
- 生成机器可读结果和面向演示的报告。
- 建立可复用的 RTL 缺陷基准与第三方许可证清单。

## 边界

- 不修改或复制 Icarus Verilog 源码。
- 不宣称与 Icarus 官方存在合作或背书。
- 不在仓库中保存模型密钥或私有端点。
- 不执行任意不可信 RTL；首版只运行仓库内受控案例。
- 自动修复仅在临时副本中验证，不覆盖原始 RTL。
- 不发布到 GitHub、PyPI，也不向第三方提交 Issue 或 PR。

## 质量与证据

模型自评不作为正确性证据。RTL 交付需要记录 compile、ast、readability、comment、naming、profile、testbench 和 toolchain 状态；功能结论必须来自真实 Icarus 仿真。
