# API Agent 本地验收记录（2026-10-04）

本轮在本地提交 `629e27c` 基础上增加 API 自动验证循环。执行环境为 Windows、Python 3.12.7、现有 Icarus 工具链。模型决策继续使用用户配置的 API；本轮没有下载本地模型、安装训练环境、训练权重或上传数据集。

## 验收范围与结果

| 项目 | 证据 / 结果 |
|---|---|
| 相关回归 | 195 项通过，55.76 秒；覆盖 AI、Agent、CLI、数据导出、网页状态及仿真流水线，非全仓库测试 |
| 真实仿真 | Agent 单元测试实际执行模十计数器正确实现与缺陷变体；有参考判据时保留反例并停止 |
| API 传输 | 测试替身验证请求计数、预算上限、失败停止和不自动重试；未向真实服务商请求 |
| 网页交互 | Streamlit AppTest 操作真实控件，模拟 API 响应并执行真实 Icarus；完成 3 次请求、2 轮仿真，切页保留结果，换设计清理旧证据 |
| 浏览器检查 | Edge 实际打开本机 8600 页面；1440×900 和 390×844 下新增区域可读，无页面横向溢出，离线配置下启动按钮禁用 |
| 类型检查 | 本轮 4 个修改或新增的业务 Python 文件通过 mypy |
| 死代码 / 编码 | 死代码扫描 149 文件、0 处；BOM 检查 0 问题 |
| 文档路径 | 新增指南、脚本和本记录纳入索引并检查存在性 |

补充了“本次未完成仿真”提示后，重新执行网页 Agent 测试，防止用户将之前的结果误认成本次产物。测试替身轨迹只写到测试临时目录，并标记为 `test_provider`，不会用于证明真实 API 效果。

## 复现命令

```powershell
python -m pytest -q tests/ai tests/core/test_agent_cli.py tests/core/test_agent_export.py tests/core/test_ui_agent.py tests/core/test_ui_provider_state.py tests/core/test_ui_input_state.py tests/core/test_ui_smoke.py tests/core/test_pipeline.py
python -m mypy src/iverilog_ai/ai/agent.py scripts/run_verification_agent.py scripts/export_agent_trajectories.py ui/app.py
python scripts/check_dead_code.py
python scripts/strip_bom.py --check
python scripts/check_doc_index.py
git diff --check
```

浏览器截图保存在本机 `.tmp-codex/agent-ui-qa/desktop.png` 与 `mobile.png`，属于被 Git 忽略的本地检查附件；干净克隆需要重新打开网页截图。当前新增界面没有检查 1920×1080。

## 尚未完成

- 真实 API 联调已在后续完成，见 `api_agent_live_2026-10-04.md`；本记录上方仍保留当时的离线验收范围。
- 真实 API 轨迹的数据质量审核、按独立模块留出的效果对照。
- 服务商托管微调及其支持模型、数据格式和费用确认。

现阶段可以称为“API 驱动的自动验证 Agent 与轨迹采集”，不能称为“训练完成的自研模型”。本轮自动化检查也不替代真人试用或独立人工审核。
