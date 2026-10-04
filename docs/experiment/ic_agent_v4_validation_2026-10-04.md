# IC Agent v4：冻结源码回归与浏览器验收

日期：2026-10-04。受测生产源码提交 `28be1edc8b84067912e2034567a8e8a5803b8184`。全部检查为机器执行，真人参与数为0；不替代 H01 试用或 H02 独立人工复核。

## 完整回归

原件目录为 `.iverilog-ai/ic-agent-v4-validation-20261004/`，逐字节副本保存在 [验收记录](ic-agent-v4-validation-2026-10-04/validation.json)。源码、测试、规格、RTL及配置共291项，执行前后 SHA256 无变化；材料有未提交更新，不声称当时整个工作区干净。

| 检查 | 实际结果 | 原件 |
|---|---|---|
| 全仓 pytest | 1075项：1073通过、2跳过、0失败、0错误；187.031秒墙钟 | [pytest.log](ic-agent-v4-validation-2026-10-04/pytest.log)、[JUnit](ic-agent-v4-validation-2026-10-04/pytest.xml) |
| mypy | 76源码文件，0错误 | [mypy.log](ic-agent-v4-validation-2026-10-04/mypy.log) |
| 未可达代码扫描 | 187文件，无发现 | [deadcode.log](ic-agent-v4-validation-2026-10-04/deadcode.log) |
| BOM与编码 | 0问题 | [bom.log](ic-agent-v4-validation-2026-10-04/bom.log) |
| 当时索引 | 169/169路径存在 | [index.log](ic-agent-v4-validation-2026-10-04/index.log) |
| diff whitespace | 退出0 | [diff.log](ic-agent-v4-validation-2026-10-04/diff.log) |

两项跳过分别为推荐断言表为空、Windows目录符号链接创建权限不足（1314）。没有把跳过算作通过；代理另以Windows junction检查路径逃逸，见[v4代理复核](../review/ic_agent_v4_proxy_review_2026-10-04.md)，该检查不补写symlink用例为通过。各次定向和历史全仓测试不相加成去重总数。

本轮在真实API烟测同时执行回归。pytest中的网络相关测试采用受控stub或本地测试服务，不产生额外付费API请求；真实模型请求仅归属[独立烟测记录](agent_comparison_v4_smoke_2026-10-04.md)。

## 实际浏览器检查

最终记录为 `.iverilog-ai/agent-v4-browser-20261004-r3/`，公开逐字节副本为 [browser/results.json](ic-agent-v4-validation-2026-10-04/browser/results.json)。实际使用Edge，打开 `http://127.0.0.1:8600/`。

- 1440×900、1920×1080、390×844三尺寸均未检测到横向溢出，功能场景控件可见并启用。手机为桌面浏览器视口模拟。
- UART离线生成和真实Icarus执行得到58/58项比对一致；进入工具设置再返回，计划和结果保留。
- 思考模式默认“自动”；“检查配置”显示官方DeepSeek Flash的实际请求配置为 `thinking_mode=disabled`。此按钮不请求模型。
- 离线模式下自动Agent启动按钮停用，避免将离线运行混称为模型调用。本次浏览器操作API请求数为0。

已查看桌面设置和手机控件截图，正文、标签、焦点和按钮可读。上传和在线Agent的交互回归由已有AppTest用例执行；本次浏览器不冒充执行了真实API按钮，也没有实体手机或真人操作证据。

首次r1脚本没有展开设置栏，r2取到了不可见的JSON组件，均保留失败记录。旧服务的模块缓存还造成覆盖控件停用；重启本机服务加载冻结源码后，r3控件正常。重启会建立新会话；页面切换保留的是同一服务会话的输入和结果，不声称进程重启保留内存会话。原全仓 `validation.json` 中 `browser_record` 指向早先r1路径，原字段未追溯改写；最终浏览器结果明确以本节r3记录为准。

## 历史和能力边界

本轮1073/2替代当前工程门禁口径，之前的914/1、1004/1、1032/1及失败日志保持历史快照。API的结构通过率、缺陷检出和参考审核由烟测另外统计；全仓测试通过不说明Agent已胜基线、不证明任意RTL正确或已完成模型训练。
