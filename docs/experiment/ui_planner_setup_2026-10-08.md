# 网页生成方式入口与配置整理（2026-10-08）

本地实现新网页会话的生成方式选择，默认选中在线模型。点击“进入配置”转到工具设置并展开对应配置，再通过“前往工作台”开始操作。同一会话切页和rerun不重复提示；新会话重新选择。进入页面或切换方式不会自动调用模型。

在线模式显示API地址、模型名称、密钥及请求参数；离线模式无需这些字段；本地调试仅显示本地服务地址。在线字段的值只保存在当前会话内，切换到其他方式时移除实际控件，切回来恢复配置。三个工作方式只在工作台创建控件，离开后保存选择，回来恢复。

## 验证

- 入口、三种配置、字段保留、工作方式范围、路径与当前规划器配置：16项通过，40.63秒。
- 其余UI冒烟、输入状态、Agent（HTTP测试替身）、行为对比、覆盖显示及资产检查：68项通过，99.50秒。
- 合计84个不同用例通过；mypy全项目88个源文件通过。
- 首轮新入口测试有1项因AppTest传入格式化显示标签失败；改为原始选项值后通过。首次类型检查有2项可空类型错误，修正后通过。失败尝试保留在对话工具输出中。
- 旧测试显式指定离线方式和已完成入口选择，避免默认改在线后产生模型请求；新增入口测试使用真正空会话验证默认在线和一次性引导。

命令使用既有锁定环境，在当前源码上运行，未升级依赖：

```text
python -m pytest -q tests/core/test_ui_planner_setup.py tests/core/test_ui_provider_state.py tests/core/test_ui_toolchain.py
python -m pytest -q tests/core/test_ui_smoke.py tests/core/test_ui_input_state.py tests/core/test_ui_agent.py tests/core/test_ui_comparison.py tests/core/test_ui_coverage_display.py tests/core/test_ui_assets.py
python -m mypy
```

## 尚未验证

实际浏览器截图没有取得。内置浏览器控制返回“failed to write kernel assets / os error 3”。独立浏览器下载先遇到cdn.playwright.dev的DNS错误；PowerShell能读到200响应头，但完整下载与范围下载分别中途断流（ResponseEnded、unexpected EOF），未取得可运行的浏览器。未将AppTest渲染当作浏览器截图，未声称完成手机或桌面尺寸的视觉验收。

本轮没有真实模型API请求，没有新增真人或H02结果。GitHub冻结f7867db和已发r1/r2/r3资料包保持原样；本地UI修改不自动进入复现人的旧克隆。此记录是作者软件检查，实际复现仍须登记运行版本、过程和结果。
