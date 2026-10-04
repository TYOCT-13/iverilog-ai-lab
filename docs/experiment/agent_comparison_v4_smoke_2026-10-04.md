# Agent v4 单次开发烟测：真实结果

源码`28be1edc8b84067912e2034567a8e8a5803b8184`，提示词`verification-agent-v4-typed-decisions`。本轮为四模块、七策略、每类正确基线与两个缺陷的一次重复，共84行。不能替代[c7版本三次重复](agent_comparison_v2_live_2026-10-04.md)，也不能把两版本画成同条件效果曲线。

## 执行与设置

原件目录：[agent-comparison-v4-smoke-20261004](../../.iverilog-ai/agent-comparison-v4-smoke-20261004/)。[预注册](../../.iverilog-ai/agent-comparison-v4-smoke-20261004/preregistration.json)、[设置](../../.iverilog-ai/agent-comparison-v4-smoke-20261004/run_settings.json)、[结果](../../.iverilog-ai/agent-comparison-v4-smoke-20261004/results.json)、[另存严格汇总](../../.iverilog-ai/agent-comparison-v4-smoke-20261004/summary.json)保持分别保存。

开始2026-10-04 14:13:32.241424 UTC，结束14:17:49.668424 UTC，约257.43秒。冻结74项代码与输入，`changed_inputs_at_finish=[]`。DeepSeek官方`deepseek-flash`、Chat Completions、显式thinking disabled、非流式、8192输出tokens、60秒超时；本轮请求cap120，实际94，未耗尽上限。

v4通过独立system/user消息与可直接校验的JSON样例明确动作结构，保持严格schema，不删除非法字段或宽松补救。实现依据与受控响应保存见[决策格式改造记录](deepseek_decision_v4_2026-10-04.md)。这同时改变消息与提示条件，不是仅覆盖反馈开关变化。

## 完整结果

| 策略 | 检出/登记缺陷 | 比例 | 请求 | total tokens | 搜索周期 | 参考审核周期 |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 7/8 | 87.5% | 0 | — | 3648 | 3648 |
| random | 8/8 | 100% | 0 | — | 3648 | 3648 |
| single | 2/8 | 25% | 12 | 22500 | 363 | 363 |
| feedback | 6/8 | 75% | 29 | 69049 | 1349 | 1349 |
| no_feedback | 7/8 | 87.5% | 27 | 56239 | 1247 | 1247 |
| protocol_random | 8/8 | 100% | 0 | — | 3648 | 3648 |
| feedback_no_coverage | 5/8 | 62.5% | 26 | 53922 | 1333 | 1333 |

每策略另有4个正确基线任务，缺陷分母始终为8。没有未开始或请求预算耗尽行。固定漏掉SPI done缺失；随机与协议随机的100%限于本开发集8个人工变体，不代表工业IP保证。

94次响应均通过动作schema校验，有效schema率94/94；拒绝0。实际总usage为201710 tokens，94次均有usage，未知usage为0，实付费用未知。schema通过只说明动作结构合法，不保证能生成测试台或检出错误。

84行终态：43 detected、40 not_detected、1 execution_error。失败为`sample-023`的正确UART基线、single策略；其唯一请求已校验且有1879 tokens，轨迹错误类型`TestbenchGenerationError`，0执行round。未依据错误类型进一步编造具体原因，未把失败改成正确通过。

严格汇总`eligible_for_frozen_comparison=false`，原因是该行没有可核验的仿真round。仍保留完整84行及每策略8个缺陷分母。其余已执行结果中正确基线假警0、变体参考重放否决0；失败的UART正确基线任务不计为已通过。

## 消融、时间与适用边界

feedback与feedback_no_coverage的8个匹配缺陷任务中：双方检出4个、仅feedback检出2个、仅无覆盖组检出1个、双方未检出1个。汇总为6/8与5/8，而no_feedback为7/8。样本只有一次重复，提案随机性独立，实际周期和请求也不相同，不能证明覆盖反馈的因果收益或统计显著。

有效检出的首反例累计周期保存在summary：feedback为14、39、44、50、9、14；这些是对应检出任务的条件值，不是所有任务的平均耗时。物理失败墙钟时间为null；结果可获得时间另列，含模型及工具过程。不能以成功任务的短时间掩盖未检出任务。

本轮显示动作格式接通，但Agent检出没有超过固定/随机基线。后续需新的独立模块、重复随机调用与稳定工具错误处理。c7版本137次拒绝和本轮1次执行失败均保留。机器试验不计入H01真人试用或H02独立人工复核；轨迹导出不代表已微调模型。

## 完整文件SHA256

| 原件 | SHA256 |
|---|---|
| preregistration.json | `b19d3c766e8759c50f49cc32a0c4ff9864ca1505f08cfac29704c90bbe02297e` |
| run_settings.json | `811999797a891ee15e434d333eff4c3330f7f3741d9e17163b48453b7ec08815` |
| results.json | `c46df250acfd2a665da204139b5b3beed7f6bba48dee847e26d2a052743b908d` |
| summary.json | `ca088434fd908b125df078b3a1f2d7672d04e2fb4da2417de5d8565df401a81a` |
| prompt/profile | `97d288f3bb800c14d52e7498fb4f16854344cb3167d07676ed5c687507a4e50c` |

全部冻结输入及逐轮日志SHA见预注册与结果原件。本记录由参与评测工具实现的机器代理整理，非独立真人审核或第三方认证。
