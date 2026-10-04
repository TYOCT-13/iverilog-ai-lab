# Agent v5 工程与浏览器验收

日期：2026-10-05。生产实现冻结提交 `4d8eafb97681eb96ffe5477b1840bb46558256fa`。本记录均为机器执行，0真人、0外部API，不替代 H01 或 H02。

## 完整回归

实际原件目录 `.iverilog-ai/ic-agent-v5-validation-20261005-r2/`；逐字节公开副本为 [validation.json](ic-agent-v5-validation-2026-10-05/validation.json)。执行前后296项源码、测试、配置及规格 SHA 均无变化。

| 检查 | 实际结果 | 原件 |
|---|---|---|
| 全仓 pytest | 1170通过、2跳过、0失败、0错误；1172项，245.01秒 | [日志](ic-agent-v5-validation-2026-10-05/pytest.log)、[JUnit](ic-agent-v5-validation-2026-10-05/pytest.xml) |
| mypy | 76源码文件，0错误 | [日志](ic-agent-v5-validation-2026-10-05/mypy.log) |
| 未可达代码 | 200文件，无发现 | [日志](ic-agent-v5-validation-2026-10-05/deadcode.log) |
| 编码/BOM | 0问题 | [日志](ic-agent-v5-validation-2026-10-05/bom.log) |
| 差异格式 | 退出0；随后新增文件暂存检查另发现两处尾空行，已删 | [日志](ic-agent-v5-validation-2026-10-05/diff.log) |

两项跳过仍为推荐断言表为空、Windows目录符号链接权限1314。没有将跳过计为通过。

完整回归结束后仅移除两份新增测试末尾多余空行；生产源码未变，相关45项测试再跑全过（4.94秒），见 [后续格式回执](ic-agent-v5-validation-2026-10-05/post-format.json)。因此不声称最终提交的全部字节与完整回归清单完全相同；生产实现一致，两份测试字节变化明确记录。完整回归开始时 HEAD 为旧提交，实际代码是未提交的工作区，清单指纹与冻结生产文件一致；提交号不能代替清单。

首次全仓验收为1168通过、2跳过、2失败：类型检查发现三文件七处标注问题，UI检查发现未执行提案表格缺固定高度。均已修复，原 [r1回执](ic-agent-v5-validation-2026-10-05/first-attempts/validation-r1.json) 保留，不以最终成功覆盖首轮失败。

## 实际浏览器

重启已确认属于本项目的8600预览服务后，用真实Edge访问 `http://127.0.0.1:8600/`。最终原件为 `.iverilog-ai/agent-v5-browser-20261005-r3/`，见 [完整结果](ic-agent-v5-validation-2026-10-05/browser/results.json)。

- 1440×900、1920×1080、390×844均无横向溢出，新补测方式及逐拍检查控件可见。手机为视口模拟。
- 默认“每轮独立运行”和“逐拍检查输出”，离线启动API Agent按钮停用。
- UART离线生成计划及真实Icarus执行58/58比对一致；切页后结果保留。
- 人为选择非默认“重放已有输入后补测”、关闭逐拍检查，进入设置再返回，选择与运行结果均保留。控件API动作另外由真实Streamlit AppTest、HTTP替身和真实Icarus回归验证，没有将替身请求算成服务商请求。

截图：[1440桌面](ic-agent-v5-validation-2026-10-05/browser/agent-controls-1440.png)、[1920桌面](ic-agent-v5-validation-2026-10-05/browser/agent-controls-1920.png)、[390手机](ic-agent-v5-validation-2026-10-05/browser/agent-controls-390.png)、[UART桌面结果](ic-agent-v5-validation-2026-10-05/browser/uart-offline-run-desktop.png)、[UART手机结果](ic-agent-v5-validation-2026-10-05/browser/uart-offline-run-mobile.png)。已实际查看控件截图，标签与按钮可读。

浏览器r1/r2在rerun后未重新展开Agent折叠区而超时，原 [r1](ic-agent-v5-validation-2026-10-05/first-attempts/browser-r1.json) / [r2](ic-agent-v5-validation-2026-10-05/first-attempts/browser-r2.json) 保留；r3显式展开后核验非默认选择。没有据自动化超时编造数据清空问题或删除失败原件。

服务重启会建立新的内存会话；输入保留结论仅针对同一会话中的页面切换和rerun，磁盘工件另行保留。未核验实体手机、真人使用、H02或异机运行。

## 代码与判据复核

[独立代理代码复核](../review/ic_v5_code_review_2026-10-05.md)记录四个实际发现及修复复判：失败列表与stdout绑定、测试台与执行指纹绑定、逐拍非法提案可恢复预检、登记路径先验证再读取。零API旧输入诊断见 [v5优化说明](agent_v5_optimization_2026-10-05.md)，在线对比另外登记，不能与本记录混成一次能力成绩。
