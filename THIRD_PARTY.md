# 第三方资源与许可证

本项目是围绕 Icarus Verilog 的**非官方**扩展，不代表官方背书，也不复制其源码。
本文件是面向开发者的简短版本；**按赛事要求编写的完整清单**（含自研边界、关键许可义务、合规状态与开放方式）见
[docs/competition/opensource_resource_list.md](docs/competition/opensource_resource_list.md)。

## 运行时

| 资源 | 版本（本机实测） | 用途 | 许可证 | 使用方式 | 核验状态 |
|---|---|---|---|---|---|
| Icarus Verilog / `iverilog`, `vvp` | 12.0 (devel) `s20150603-1110-g18392a46` | 编译与仿真 | GPL-2.0-or-later | 独立进程调用，不修改、不复制、不再分发 | ✅ 已核验 |
| Python | 3.12.7 | 运行时 | PSF License Agreement | 运行本项目代码 | ✅ 已核验 |
| pydantic | 2.8.2 | 测试计划 JSON 校验 | MIT | 库依赖 | ✅ 已核验 |
| Streamlit | 1.37.1 | 演示页面（可选 `[ui]`） | Apache-2.0 | 库依赖 | ✅ 已核验 |
| Yosys / YoWASP Yosys | 0.69（`yowasp-yosys` 0.69.0.0.post1233） | 综合证据层（可选） | ISC | 独立进程调用，不修改、不复制、不再分发 | ✅ 已核验 |

## 可选人工复核

| 资源 | 版本 | 用途 | 许可证 | 核验状态 |
|---|---|---|---|---|
| GTKWave | 3.3.108 | 波形人工查看（核心流程不依赖） | GPL-2.0-or-later | ✅ 已核验 |

## 开发与测试

| 资源 | 版本 | 用途 | 许可证 |
|---|---|---|---|
| pytest | 7.4.4 | 回归测试 | MIT |

## 人工智能服务

模型服务**不是**本仓库的依赖。默认路径不调用任何模型：网页规划器默认是进程内的离线确定性规则引擎（按 DUT contract 生成计划），库层缺省 provider 是离线 `MockProvider`；兼容 provider 只有用户显式设置环境变量后才请求。仓库不含密钥，不主动联网（回环地址上的本地调试模型服务除外）。

## 数据与素材

内置 RTL 参考设计与缺陷变体、testbench、规格、contract、缺陷基准和实验数据由本项目编写或产生。外部复现实验另使用 `verilog-uart` / `verilog-axi` 的 MIT 源码，按来源清单下载到被 Git 忽略的 `.iverilog-ai/external/`；这些上游源码不随本仓库分发，见 `docs/experiment/external_modules.md`。

网页附带 **Anton** 字体（`ui/assets/fonts/Anton-Regular.ttf`），来源为 Google Fonts / The Anton Project Authors，使用 **SIL Open Font License 1.1**。字体保持未修改，版权与完整许可随包保留在 `ui/assets/fonts/OFL.txt`。原创 SVG 主视觉位于 `ui/assets/verification-map.svg`；页面未使用明日方舟的 Logo、角色或官方设备图片。

`verification_rules/` 归纳自公开开源资料的工程约定（lowRISC 风格指南、verilog-axi、verilog-ethernet、cocotb、LiteX、ZipCPU wb2axip、Project F），**仅参考工程原则，未复制任何代码**；来源与提炼原则见 `verification_rules/opensource_synthesis.md`。
