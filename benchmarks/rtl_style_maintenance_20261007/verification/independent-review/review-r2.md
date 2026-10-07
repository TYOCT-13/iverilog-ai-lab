# RTL 维护发布版独立只读复核（二版）

结论：passed_with_limits。审核者为未编写候选 RTL/wrapper 的 AI 子代理；本文件不构成 H02 真人审核。

完成 1511 项机械检查，1511 项通过，0 项失败。数量含同一文件跨绑定、复制和归档边界的重复核查，不是独立样本数。

原975项初审两处失败由审核者文本读取边界错误引起：Windows重放文件CRLF与原LF字节不同。按wrapper实际read_text通用换行口径，两份脚本都仅8处路径改写，余下文本/AST相同。二版前两次追加尝试错误假设ZIP命令根映射，均在写结论前停止；失败记录保留，源和原件未改。

- 35必需输入、2合约和入口哈希；6原RTL与冻结源逐字节一致。6新RTL端口、状态形状/初值、时钟复位沿一致，B/C故意缺陷保留。
- 64首次复制记录、640+33归档成员；追加473公开重放成员ZIP和36复制记录，全部逐字节核对。
- 18份规格MD/WaveJSON/SVG公开重建字节相同，3完整规格输入与6WaveJSON一致。
- 公开36次DUT，18组原/新3726行对照、171+4944=5115输出值相等；36观测包与首次验证对应包也一致。总72为同组重复。
- 新报告、包README及四份当前索引口径与实际回执一致；原12问题、API成绩和v3材料保留。

| 官方 gate | 首次候选原件 | 公开重放原件 |
|---|---|---|
| compile | passed | passed |
| ast | passed | passed |
| readability | passed | passed |
| comment | passed | passed |
| naming | passed | passed |
| profile | passed | passed |
| testbench | not_requested | not_requested |
| toolchain | not_requested | not_requested |

## 限制

- 本审核是未编写这些 RTL 的 AI 子代理只读复核，不是 H02 真人审查、真人试用或异机复现；审核者没有重新运行 gate、DUT、API、联网、安装或凭据读取。
- 公开 all 是对同一套向量的第二次维护验证。36 + 36 = 72 次 DUT 执行不增加独立验证场景数；每轮 18 组原/新比较、5115 个输出值对照，不能称为新模型实验样本。
- 八项官方 gate 中只有六项静态检查 passed；testbench/toolchain 原件仍为 not_requested。真实 Icarus 执行应单独引用本地日志。四态驱动 0 内建断言且 executor_verdict inconclusive，passed 来自脚本外层显式比较。
- 接口、状态形状与时钟复位结构一致，加上所测二/四态样本相等，可支持维护版在所测范围内保持行为；没有形式等价、综合、物理时序、硬件或穷尽状态证明。
- 新维护源码的格式和注释不同，旧 108 任务/87 API 的 Agent 分数不能自动迁移到它；本轮无模型 API 实验。
- 入口清单绑定公开输入、两个 DUT 合约和入口哈希；没有冻结全部项目 Python 实现和安装技能运行时。当前本机同一工作树重放成功不等于跨版本或异机已验证。
- publication_copy_manifest.json 保留了发布复制阶段 public_all_replay_not_yet_run=true；之后的实际 replay_receipt.json status passed 是追加证据，不应修改原阶段回执。
- 本审核核对 6 份最终 SVG、WaveJSON、规格和公开重生成物绑定；没有把作者的浏览器截图检查改称本审核者人工视觉复核。
- 初版两处失败由审核脚本文本读取口径错误引起：原脚本LF、Windows重放文件CRLF。按wrapper实际read_text通用换行语义，原8处路径映射外剩余文本及AST完全一致。初版失败记录保留。
- 二版前两次追加尝试分别错误假设ZIP只有一个根、虚拟命令根就是preflight实际目录。失败JSON/MD保留；本版按manifest实际记录的6个.tmp-codex命令文件来源核对全部473成员。

审核者未启动gate、DUT、API、安装、联网、凭据读取或Git。完整输入指纹、各机械检查和审核失败解释见review-r2.json。
