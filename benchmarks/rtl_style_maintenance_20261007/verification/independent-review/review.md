# RTL 维护发布版独立只读复核

结论：failed。审核者为未编写候选 RTL 和 wrapper 的 AI 子代理；本文件不构成 H02 真人审查。

完成 975 项机械检查，973 项通过，2 项失败。计数包含同一文件在不同绑定/归档/复制边界的重复检查，不是独立实验样本数量。

- 核对 35 个公开必需输入、2 份既有合约、入口哈希、64 个复制记录、640 + 33 个归档成员，以及原始 6 个 RTL 与冻结实验源的逐字节一致性。
- 6 个新模块的端口、寄存器类型/宽度/初值和时钟复位触发结构一致。仅计数内部寄存器重命名；未增加寄存器和采样沿。B/C 故意缺陷仍保留。
- 3 份正确完整规格输入与 6 份 WaveJSON 一致；公开重放产生的 6 份 Markdown、6 份 WaveJSON、6 份 SVG 共 18 文件逐字节一致。
- 两份语义脚本每份仅 8 处路径改写，精确重构后与实际执行脚本相同；向量、判据、比较逻辑和其余文本未变。
- 公开重放实际记录 36 次 DUT 执行，18 组原/新比较，3726 行观测、5115 个输出值相等。36 个公开观测包还与原运行对应包相等；这是同一验证的重复运行。

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

## 限制与原始状态

- 本审核是未编写这些 RTL 的 AI 子代理只读复核，不是 H02 真人审查、真人试用或异机复现；审核者没有重新运行 gate、DUT、API、联网、安装或凭据读取。
- 公开 all 是对同一套向量的第二次维护验证。36 + 36 = 72 次 DUT 执行不增加独立验证场景数；每轮 18 组原/新比较、5115 个输出值对照，不能称为新模型实验样本。
- 八项官方 gate 中只有六项静态检查 passed；testbench/toolchain 原件仍为 not_requested。真实 Icarus 执行应单独引用本地日志。四态驱动 0 内建断言且 executor_verdict inconclusive，passed 来自脚本外层显式比较。
- 接口、状态形状与时钟复位结构一致，加上所测二/四态样本相等，可支持维护版在所测范围内保持行为；没有形式等价、综合、物理时序、硬件或穷尽状态证明。
- 新维护源码的格式和注释不同，旧 108 任务/87 API 的 Agent 分数不能自动迁移到它；本轮无模型 API 实验。
- 入口清单绑定公开输入、两个 DUT 合约和入口哈希；没有冻结全部项目 Python 实现和安装技能运行时。当前本机同一工作树重放成功不等于跨版本或异机已验证。
- publication_copy_manifest.json 保留了发布复制阶段 public_all_replay_not_yet_run=true；之后的实际 replay_receipt.json status passed 是追加证据，不应修改原阶段回执。
- 本审核核对 6 份最终 SVG、WaveJSON、规格和公开重生成物绑定；没有把作者的浏览器截图检查改称本审核者人工视觉复核。

## 失败检查

- path_only_rewrite: public-oracle eight guarded replacements, no other byte edits after UTF-8/BOM decoding
- path_only_rewrite: four-state eight guarded replacements, no other byte edits after UTF-8/BOM decoding

本审核未启动新 gate、DUT、API、安装、联网、凭据读取或 Git 操作；仅在本目录追加 JSON 与 Markdown 记录。完整证据绑定和每项检查见同目录 review.json。
