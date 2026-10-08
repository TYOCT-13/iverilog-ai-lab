# GitHub代码上传确认（2026-10-08）

公开仓库为[TYOCT-13/iverilog-ai-lab](https://github.com/TYOCT-13/iverilog-ai-lab)。提交者完成推送后，实际Git远程读取确认main为 **f7867db67cde354e8664205b0470ade8ba18dc17**，与当时本地main一致。

用户提供的首次日志有HTTP408及断连；最后一次日志显示新建远程main并建立跟踪。成功结论依据实时Git远程提交，不依据首次失败后单独出现的Everything up-to-date。

只读核验及本轮文档检查见[回执](repository-publication-2026-10-08/receipt.json)。先前[建仓记录](repository_readiness_2026-10-08.md)和回执保存的是上传前的空仓库状态，继续按当时版本留存。

本轮网页读取工具仍返回旧空仓库内容，tree/main读取也失败，未据此声称看到了新的网页截图。Git远程提交可确认已上传；另一个人实际下载、安装、运行、反馈及外部Action调用仍分别待验证。

## 交给复现人的材料

- [当前复现指南](../reproduce_current.md)：GitHub克隆、固定已上传代码、锁依赖、离线矩阵、网页与可选进阶。
- [空白记录表](../trial/forms/reproduction_record.md)：环境、实际操作、首次失败、帮助和确认。
- [可发送资料包](../trial/reproduction_guide_2026-10-08.zip)：仅说明、空白表和参与者任务，不包含真人原件、模型凭据或软件安装器。

资料包是知晓预期结果的工程复现说明，不是严格盲测。若组织首次可用性试用，只发送参与者入口与分配的任务卡，不提前发送组织者检查答案。

代码固定f7867db；本轮新增指南可通过附件发送，保存本地提交不等于已推送这些新增文档。本轮没有执行git push，也没有新模型API或DUT实验；先前API批次、失败分母和v3材料按原版本保留。
