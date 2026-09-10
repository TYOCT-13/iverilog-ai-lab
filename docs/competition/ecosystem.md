# 开源生态建设说明

Icarus智测是围绕 Icarus Verilog 的非官方 AI 验证扩展，补充测试规划、结构化报告、RTL 缺陷基准、可复用 CI 工作流和中文教学案例。Icarus 负责真实编译与仿真；本项目负责上层自动化能力。

## 可复用成果

- `TestPlan` JSON Schema：模型输出进入执行器前的唯一合同；
- 离线 MockProvider：无密钥、可复现的演示和测试依据；
- OpenAI-compatible provider：通用适配，不绑定厂商；
- 后续 GitHub Actions/测试基准，供其他 RTL 项目接入；
- 中文文档与许可证清单。

## 合规边界

不修改 Icarus 源码、不宣称官方合作、不执行任意不可信 RTL、不保存模型密钥、不发布或提交上游 Issue/PR。功能结论必须来自真实仿真，模型自评不是正确性证据。
