# 协议规格与判据补全：2026-10-04

本轮完成四个内置验证案例的完整规格，修复正确 FIFO 基线中的同拍读写计数问题，并补全外部 UART TX 的位持续时间与 busy 释放检查。以下均为本地真实 Icarus 执行，API 请求数为 0；不是真人试用、独立人工复核或 Agent 检出率提升实验。

## 1. 完整规格和预算接口

新对照试验读取 [agent_protocols.json](../../spec/agent_protocols.json)，schema 为 `agent-protocols-v1`。每个 `cases` 项提供 `spec_path`、`cycle_budget`、`default_parameters`、`input_defaults`、`timing_basis`、结构化 `timing`。规格文本以对应 Markdown 为唯一来源，不再只给模型一句案例简介。

| 案例 | 完整规格 | 固定验证参数 | 累计激励周期上限 | 时序依据 |
| --- | --- | --- | ---: | --- |
| sync_fifo | [FIFO](../../spec/sync_fifo_spec.md) | DATA_WIDTH=8，DEPTH=4 | 160 | 逐周期操作、空满拒绝、同拍接受净 0、重复指针回绕 |
| uart_tx | [UART TX](../../spec/uart_tx_spec.md) | CLKS_PER_BIT=4 | 512 | E0 接受，E40 释放 busy；至少 41 个采样边沿覆盖一次完整事务 |
| spi_master | [SPI 示例](../../spec/spi_master_spec.md) | WIDTH=8 | 384 | E0 接受，E15 done/busy 结束，E16 空闲恢复 |
| handshake_stage | [握手级](../../spec/handshake_stage_spec.md) | WIDTH=8 | 160 | 按边沿前 ready/valid 接受，反压保持，同拍消费并补入 |

预算是多轮累计的激励周期上限，不含测试台自动初始复位。各策略统一预算，但向量数、输出采样数、参考基线审计和实际累计执行周期需要分别记录。扩大预算本身不证明 AI 改善。

SPI 规格明确记录此教学实现的边沿后 MOSI 更新关系；本模块没有 CS、MISO 或可配置 CPHA/CPOL，不能把通过寄存器行为检查写成标准 SPI 时序认证。FIFO 指针固定 2 位，本轮仅验证 DEPTH=4，不外推其他参数。

## 2. FIFO：先按独立规格重现，再同时修复 RTL 和模型

旧 `rtl/sync_fifo.v` 同拍接受写和读时先后执行两条 `count` 非阻塞赋值，最后的读赋值覆盖写赋值，把占用量减 1。旧参考模型也兼容了这一错误。模型与 RTL 一致并不能替代协议正确性检查。

本轮使用 Python `deque` 作为独立 FIFO 规格：根据边沿前的占用量决定是否读/写，先取出旧队首再加入新项；不复制 RTL 的指针、计数寄存器或非阻塞赋值结构。激励覆盖空时同拍读写、满时同拍读写、中间占用同拍读写、5 轮填满排空、满时拒写、空读保持、占用时复位及复位后重发。

| 实际执行的输入 | 周期 | 输出比较数 | 与独立队列的差异数 |
| --- | ---: | ---: | ---: |
| 修复前正确基线原件 | 76 | 228 | 66 |
| 修复后正确基线 | 76 | 228 | 0 |
| 新单点 full_off_by_one 控制项 | 76 | 228 | 56 |
| 新单点 write_when_full 控制项 | 76 | 228 | 46 |

旧基线首次输出差异在本激励的第 6 个零起始周期：full 实际为 0，队列规格应为 1；随后第 9 周期提前 empty，第 10 周期读数据实际 0x84、期望 0xA5。修复后所有 228 个比较一致。

修复把 RTL 的 count 更新合并为一次：只有接受写时加 1，只有接受读时减 1，两者均接受或均拒绝时保持。参考模型改为同样的净变化公式，但仍必须通过独立队列规格和真实 RTL 双重检查。空和满边界继续按边沿前标志决定接受，满时读不会使同一拍写请求追溯变成接受。

### 新试验中的单点变体来源

旧两个 FIFO 变体继承了旧基线的计数问题，不适合作为修复后单缺陷对照。本轮保留它们不动，在 [benchmarks/agent_v2](../../benchmarks/agent_v2/mutation_manifest.json) 冻结修复后的参考快照，并只应用原清单前两个 mutation operator：

- `fifo_bug_full_off_by_one`：`assign full=(count==DEPTH);` 替换成 `assign full=(count==DEPTH-1);`。
- `fifo_bug_write_when_full`：`if(wr_en&&!full)` 替换成 `if(wr_en)`，仅去掉内存写门控。修正后的计数接受逻辑不变，错误仍会破坏存储/写位置并在后续读出时显现。

每个新候选相对新基线恰好一次 anchor 替换，其他源字节完全相同；不是在复合故障基础上重新贴“单点”标签。测试还确认两项候选在复位、空时接受和中间同拍读写的非目标片段满足规格。两项 ID 和开发集缺陷数量沿用旧清单，其他六个样本不变，原 8 项分母不增减。

manifest schema 为 `agent-v2-mutations-v1`，含基线祖先 Git commit（在本次修复之前）、新基线快照与 SHA、旧候选 SHA、单处突变位置与 operator、新候选 SHA。尚未提交的新基线不伪造提交号；精确复现以冻结快照 SHA 为准。

| 来源 | SHA-256 |
| --- | --- |
| 新正确 FIFO 基线/快照 | `964cd554041818533ece195f3abcc6979c116c4a3d72106a7fe49c503bd2dadc` |
| 新 full_off_by_one | `64421ef7e99f0d0e4964a680067a7e2d4773c12d15d9b65d8d120156adf8418a` |
| 新 write_when_full | `4d6888893636961465ab503be921859f97d3c0c15695ababaae7ce103032420c` |
| 新变体 manifest | `5ca8faef783e5d3a3a30ceed4a137353917c767dd7650966e8e4cdb93b7067eb` |

## 3. 外部 UART TX：环回成功不能替代精确计时

先按旧判据重新执行 3 个模块、24 个冻结输入：3 个正确基线、15 个历史人工变体、3 个等价改写、3 个编译失败控制项。UART TX 的 `mut_prescale_off_by_one` 和 `mut_busy_never_clears` 仍然全部通过旧 SPEC；verify-diff 已经能发现它们与基线不同。

原因分别为：接收器环回有采样容差，缩短一拍仍可能解码成功；旧等待任务只等到超时后返回，没有断言 busy 是否真的清除。这两项是测试判据的缺口，不是候选与规格一致。

新判据保留环回数据检查，并新增独立的端口级计时：

- 用相邻位交替的 0x55 发送完整 8N1 帧，分别在 `prescale=1` 和 `prescale=2` 下按每个 clk 周期检查 txd 的期望窗口。
- 外部冻结模块每个起始/数据位持续 `8*prescale` 周期；其停止位的 busy 保持为 `8*prescale+1` 周期。这是该冻结实现的明确完成约定，不是对所有 UART 的通用规定。
- 到计算出的完成期限直接断言 busy 释放、ready 恢复，忙期间断言 ready 为低，不能以“等到超时继续”冒充通过。
- 在 negedge 驱动输入，在 posedge 后 `#1` 采样，避免测试台与 DUT 的 NBA 更新竞争。设置整体超时保护。

| 同字节冻结控制项 | 旧 SPEC | 新 SPEC | verify-diff |
| --- | --- | --- | --- |
| prescale_off_by_one | 0 失败，漏检 | 22 次断言失败，检出 | 两版均 different |
| busy_never_clears | 0 失败，漏检 | 6 次断言失败，检出 | 两版均 different |
| UART TX 正确基线 | 全过 | 773 检查，0 失败 | 两版均 identical |
| UART TX 等价改写 | 全过 | 773 检查，0 失败 | 两版均 identical |

完整 24 输入重放的 SPEC 检出从 **13/15** 变为 **15/15**；3 个正确基线、3 个等价控制项均无误报；3 个编译失败控制项仍归为 inconclusive。UART RX 仍为 11 检查、优先编码器仍为 25 检查，新 UART TX 为 773 检查。断言次数不是独立样本量。

verify-diff 结果保持 **15 different / 6 identical / 3 inconclusive**。重放前后全部 24 项 candidate SHA 完全相同，未修改外部 DUT、旧变体或等价原件。批次 CLI 退出 0 表示预期输入均取得完整结果，不表示 24 份 RTL 都正确。

这证明人工规格判据补全有效。15 项都是已知的开发集历史人工变体，同作者两个仓库；不属于未见过的独立保留集，不是 AI 新发现 15 个真实工程缺陷。

## 4. 实际验证与原始产物

工具为本机 Icarus Verilog 12.0，Python 3.12.7。最终针对性回归命令：

```powershell
& D:/Users/TYOCT/anaconda3/python.exe -X utf8 -m pytest -q `
  tests/core/test_external_module_harness.py `
  tests/core/test_agent_protocol_specs.py `
  tests/core/test_reference_model_alignment.py `
  --basetemp .tmp-codex/pytest-protocol-oracles-v2-final-controls
```

实际结果 **46 passed，9.91 s**。包括 15 模块每项 4 个 seed 的逐拍模型/RTL 对齐、FIFO 独立队列、两项新单点控制及非目标片段，以及外部 UART 计时任务在独立脚本波形发射器上的正确/缩短位周期/busy 不释放/停止位错误控制。测试夹具中的脚本波形不是外部检出成绩的新增样本。

外部重放实际命令（先运行旧判据保存 before，再修改测试台，再运行 v2）：

```powershell
& D:/Users/TYOCT/anaconda3/python.exe -X utf8 scripts/check_external_module.py `
  --manifest .iverilog-ai/external/frozen-20261004-ic/manifest.json `
  --existing-cases .iverilog-ai/external/replay-20261004-ic-final `
  --output-dir .iverilog-ai/external/replay-20261004-protocol-v2 `
  --iverilog D:/iverilog/bin/iverilog.exe --vvp D:/iverilog/bin/vvp.exe
```

再次运行必须使用全新输出目录；当前脚本使用新判据，旧判据应从 before 目录内已经保存的 TB 原件独立重放，不能把再次执行新脚本得到的结果称为旧判据。

| 原始目录 | 内容 |
| --- | --- |
| `.iverilog-ai/external/replay-20261004-protocol-before` | 旧 SPEC 的 24 输入，冻结输入、TB、编译与仿真日志、verify-diff、artifact SHA |
| `.iverilog-ai/external/replay-20261004-protocol-v2` | 新 SPEC 的同 24 输入，完整 773 次检查及原始日志 |
| `.iverilog-ai/protocol-oracle-fifo-20261004-before` | 修复前 FIFO、独立队列期望与实际 76 周期输出、66 差异 |
| `.iverilog-ai/protocol-oracle-fifo-20261004-after-final` | 新 FIFO 的 canonical LF 字节、同规格 228 比较零差异 |
| `.iverilog-ai/protocol-oracle-fifo-20261004-full-off-by-one` | 新单点满标志控制项，56 差异 |
| `.iverilog-ai/protocol-oracle-fifo-20261004-write-when-full` | 新单点满时写入控制项，46 差异 |

初步修复验证另保存在 `.iverilog-ai/protocol-oracle-fifo-20261004-after`；随后将新基线规范为 LF 并冻结 manifest，再在 after-final 重放。两个修复后结果均为零差异，原件均保留。

| evidence.json | SHA-256 |
| --- | --- |
| external / before | `4ec5ff66046a79e9a6c1bcb6d09ed8e2cdf828d0b6eb037d770ea5b96d9123da` |
| external / v2 | `d392f4a582f30f5551848b519c86d5a628be7f44f002d4f8e9418645e6b7f3cb` |
| FIFO / before | `220a5fd98db833a5d6d5608a7e66d0902cafb5acdc60e085e5ddbbef58edee93` |
| FIFO / after-final | `159d827d6905ddd2ffbe35f4390ee32c5be2a9197c551d673dc7bf0fc6281beb` |
| FIFO / full-off-by-one | `7218e17b96a140e1ba1f10defc3343d660152eb4e20ccef1c672c3496ab167e5` |
| FIFO / write-when-full | `e6a5a59ad651ca513da2caa4694110fddc58149211126439ae78faeec1fddb00` |

## 5. 后续使用边界

新比较 profile 应使用修复后的 FIFO 基线和新两个单点变体，旧 profile 及旧实验档案继续保留旧来源。由于本轮同时改了 RTL、判据、完整规格、预算和采样组织，不能把新旧检出率差直接归因于功能覆盖反馈或 API。

本轮未调用付费 API、未替换模型推理方式、未生成真人/人审结果、未改写历史 4/8、5/8 或原 PDF，也未重新封装先前已经冻结的大证据包。新报告中的结果只能引用本轮明确版本化的记录。
