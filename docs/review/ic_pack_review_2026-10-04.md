# 本地 IC 证据包代理只读审计（2026-10-04）

审计身份：Codex 子代理；参与过内部 pilot 实现、统计和指标文档编写，存在作者关系。本记录是代理取证检查，**不是独立人工审核，也不是异机独立复现或真人试用**。

本轮直接打开 ZIP，重新计算字节哈希、执行 CRC 检查并读取包内原始证据；没有仅抄回执。未修改包、清单、源码、原始实验或其他文档；未调用 API、未读取密钥文件。报告生成于包完成后，不在本次已冻结 ZIP 内。

## 结论与对象

在本次检查范围内，**包与清单没有发现未解释的不一致**。四份注册输入快照与原始预注册/metadata 的 424 项 SHA256 全部匹配。另有 36 项源码 ZIP 与 Git blob 的原始字节不同，逐项证实只是 `.gitattributes` 指定的 CRLF 转换，见下文；不能笼统说所有源码归档字节均与 Git blob 相同。

- 包：`E:/FPGA_WORK/iverilog-ai-lab/.iverilog-ai/ic-evidence-pack-20261004.zip`
- 实际大小：**86,376,627 字节**。
- 实际重算 SHA256：`1d91d09309f45e978cddbb5001bbde022cfc4fbb03b414c7e78346b14a9bf15f`，与回执一致。
- 回执：`.iverilog-ai/ic-evidence-pack-receipt-20261004.json`，SHA256 `d2da190e6cf5e772b5c57cd8a2401910b9e6e816150864a63feb45a795dbe557`。
- 材料提交：`81114bce3f3bb72e2e2a05969b15200c1a4ae767`；最终受测源码提交：`867b8bd564c881954c98cc18813884a4074d1ed5`。两者与回执、包清单一致。

## 全包实际检查

| 检查 | 实际结果 |
|---|---|
| 外层 ZIP CRC | `ZipFile.testzip()` 返回 None；未发现 CRC 错误 |
| 文件集合 | 实际 **41,007 项**；清单 **41,006 项**加 manifest.json，集合严格相等，无重复项 |
| 路径 | 未发现绝对路径或 `..` 路径分量 |
| 每文件 SHA256 和长度 | **41,006/41,006** 与 manifest 逐项一致 |
| 内嵌源码 ZIP | 6/6 的 CRC、ZIP comment、路径中的提交、清单 commit 均对应 |
| 注册工作区输入 | 4 子清单、424 文件，集合、长度、SHA256 与包内原始注册记录一致 |

manifest.json 自身不列在自己的文件指纹表内；它受到整包 SHA256 的约束。本次验证不将回执中 `credential_value_scan_passed` 视为独立重做的密钥扫描结果；没有读取凭据来复做该扫描。

## 六份源码快照

除 comment/提交/清单对应关系外，还读取本地相同 Git commit 的 `ls-tree`，逐文件比较 ZIP 内容计算得到的 Git blob OID。六归档的文件集合均与对应提交一致，共检查 2,877 项源码文件；每个 commit 均能解析为同一个完整 commit ID。

| Git commit | 归档文件数 | ZIP comment / 清单对应 | 与 Git blob 仅 CRLF 不同 |
|---|---:|---|---:|
| `0de10a07c2b5af29729f624e0af093693928c84f` | 470 | 一致 | 6 |
| `e9b7b8aa0ef6b78c1871abb7fe4e33c2b2abec2a` | 473 | 一致 | 6 |
| `9fbfb9be399957d95f41cbe366b5cd659f4d7f55` | 474 | 一致 | 6 |
| `1c1e0dc5b30a65a83673951cc495b1a7b700511c` | 475 | 一致 | 6 |
| `867b8bd564c881954c98cc18813884a4074d1ed5` | 475 | 一致 | 6 |
| `81114bce3f3bb72e2e2a05969b15200c1a4ae767` | 510 | 一致 | 6 |

每份归档的六个路径均为：`scripts/make_shortcuts.ps1`、`start_ui.cmd`、`start_ui.ps1`、`stop_ui.cmd`、`stop_ui.ps1`、`tools/service_panel/build.ps1`。每一处都实际核对：归档和 Git blob 将 CRLF 归一化为 LF 后字节相等，且该归档内 `.gitattributes` 对相应扩展名明确指定 `text eol=crlf`。这是已解释的导出换行差异，不是包与 manifest 的指纹不符；36 处原始字节差异仍如实记录。

## 四份注册输入快照

将子清单的 `.iverilog-ai/...` metadata 路径映射成包内 `raw/...`，先核对 metadata 文件本身 SHA256，再读取指定字段中的原始每文件哈希。子清单路径集合必须与该字段严格相等；快照内容按原始注册字节逐项计算，不先归一化换行。另从对应 `source/<commit>.zip` 读取 canonical 字节，逐项比较子清单的 `git_canonical_sha256` 和 `git_blob_oid`。

| 快照 | 项数 | 原始包内注册来源 | 工作区字节与 canonical 不同项 |
|---|---:|---|---:|
| final_pdf_validation | 148 | `raw/ic-validation-pdf-final-20261004/metadata.json` | 33 |
| interrupted_pilot | 64 | `raw/agent-comparison-live-20261004/preregistration.json` | 29 |
| sampling_guard_validation | 148 | `raw/ic-validation-sampling-guard-20261004/metadata.json` | 33 |
| valid_chat_pilot | 64 | `raw/agent-comparison-live-chat-v2/preregistration.json` | 29 |
| 合计 | **424** | 4 份来源分别核对 | **124** |

424 项的注册字节 SHA、canonical SHA、Git blob OID 与子清单全部吻合。124 项工作区/canonical 差异也与 `canonical_bytes_differ` 标记一致，不把 Git 归档替代原始注册字节。这里的 124 项属于四注册集合的重复计数口径，不是 124 个全仓唯一文件，也不同于上一节六源码快照中的 36 处 CRLF 导出差异。

## 原始实验与最终测试抽查

- 有效 pilot：包内 `raw/agent-comparison-live-chat-v2/results.json` 确有 **60 行**、**52 请求**和真实 `finished_at=2026-10-04T07:11:32.803894+00:00`。本次是包内存在性/状态抽查，不重新跑模型或重算全部实验判据。
- 首次中断：`raw/agent-comparison-live-20261004/results.json` **没有 finished_at**，60 行中 **47 行 not_started**、已落盘请求数 7。没有把中断运行伪装为完整实验；该数不能当作服务商完整账单。
- 最终 PDF 后源码回归：读取 `raw/ic-validation-pdf-final-20261004/pytest.log`，末行 **914 passed, 1 skipped in 227.34s**。JUnit 实际为 tests=915、failures=0、errors=0、skipped=1，换算通过 914，与日志一致。这里的 227.34 秒属于最终 `867b8bd` 回归，不混用早前 `1c1e0dc` 的 211.47 秒。

## 记录与限制

另只读核对包完成后的本机离线冒烟记录 `docs/experiment/ic-pack-smoke-2026-10-04/smoke.json`、`stdout.log`、`stderr.log`：两日志实算 SHA256 均与 smoke.json 相符，stdout 的 qualified_baseline_differential 观测为 **547 个输出比较、0 差异**，stderr 为空；记录显示应用退出 0、0 API 请求，源码来自本包 materials commit 的解压目录。首次取证辅助脚本误查不存在的 `evidence_kind` 字段触发 KeyError，记录已说明按真实 `expectation_source` 字段修正读取，未重新运行仿真；不能将此辅助取值错误称为应用仿真失败。此次只读审计没有重复执行该冒烟，它也只是同机已安装环境的包内源码运行，不是异机独立复现。

只读辅助脚本：`.tmp-codex/audit_ic_pack_readonly.py`；机器输出：`.tmp-codex/ic_pack_readonly_audit.json`。脚本直接读取包、回执和本地 Git 对象，不需要密钥。运行可复核上述集合、CRC、SHA、Git OID、注册映射及样本日志；这些辅助文件不在本次冻结包中。

本次没有在另一台机器解压并重新执行 914 项测试，没有重做各实验或检查所有业务结论，没有执行二进制仿真工件，也未验证外部托管下载地址、真实 GitHub Actions 或真人操作。哈希一致说明收到的工件与冻结清单一致，不能单独证明实验方法有效、服务商身份、真人参与或模型能力提升。作者关系不因更换一个代理而变成独立人工审核。
