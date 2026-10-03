# 本地验证记录（2026-10-04）

本轮修正文档、重汇总已有实验，并增加小规模 API 接入入口。日期采用北京时间；本轮没有发起付费模型请求，也没有修改原始十轮实验。

## 版本与范围

- 分支：`codex/competition-reconcile-20261004`；基线提交：`2ef75da`。下述测试对应基线之上的实验、API 和材料修改，最终本地提交可通过本文件的 Git 历史定位。
- Python：3.12.7；Windows 本地环境，调用已安装的 Icarus。测试子进程移除常见 API 密钥变量，并设 `IVERILOG_AI_ALLOW_NETWORK=0`；回环调试服务仍用于接口验证。
- Python 源文件指纹：`7772bcfaf7cfa41def9f4327b870221b183821b8fea2a39576d1e1e32cf574d0`。按 `src`、`ui`、`scripts`、`tests` 顺序，对每目录按路径排序的 `.py` 文件累加仓库相对路径 UTF-8 字节和文件字节后计算 SHA-256。
- 原始实验 SHA-256 保持 `91dabfdf4038bb72a778cee9e75b197ca4d982d2f3b5a0692220ef5dc9dbe105`。

## 实际结果

| 检查 | 结果 | 证据 |
|---|---|---|
| 全量 pytest | **768 passed / 1 skipped / 0 failed**，150.44 秒 | `docs/experiment/local-validation-2026-10-04/pytest.log` |
| mypy（src / ui / scripts） | **64 个源文件，0 错误** | `docs/experiment/local-validation-2026-10-04/mypy.log` |
| 最终 PDF 排版调整后复核 | **9 passed**，含两份 PDF 与 Markdown 的逐页文本一致性 | `docs/experiment/local-validation-2026-10-04/validation.json` |
| API 本地实际联调 | **1 次 HTTP 请求、10 条向量、30 次检查、0 失败**；调用的是确定性调试服务 | 同上 `api_local_smoke`，不是真实模型效果或计费数据 |
| 报告 PDF | **27 页 / 正文 22 页 / 946,980 字节**；0 error / 1 warning | `docs/experiment/local-validation-2026-10-04/submission_pdf.json` |
| 功能总览 PDF | **10 页 / 427,389 字节**，与源文件一致 | `docs/project_overview.pdf` |
| 仓库提交体检 | **1 error**：CITATION 的公开地址待补 | `docs/experiment/local-validation-2026-10-04/submission_repo.json` |

唯一跳过项是推荐断言表当前为空，见 `tests/core/test_rule_assertions.py:55`。最初回归为 766 通过、1 跳过、2 失败；失败均因 PDF 仍是旧稿。重新导出后全量回归得到上述 768 通过，之后仅调整附录分页并重跑 9 项 PDF 测试，Python 源文件指纹保持一致。

已渲染全部 PDF 页面检查版面，并放大核对实验表格和最后一页；无页面越界文字，元数据身份字段为空。报告正文 22 页仍超过建议的 15 页；这项 warning 保留，不声称已经满足建议篇幅。

复现命令（临时目录应选在仓库外）：

```powershell
python -X utf8 -m pytest -q --basetemp=<仓库外临时目录>
python -X utf8 -m mypy src ui scripts
python scripts/check_submission.py --repo .
python scripts/check_submission.py docs/competition/technical_report_draft.pdf --kind report
```

## 已知交付缺口

当前按用户选择只保存本地 Git。真实公开 URL、另一个仓库的 Actions 执行、真人试用、外部变体独立人工审核及演示视频仍待完成。CITATION 占位字段继续由门禁报告，本地提交不等于完成开源发布。

API 入口已通过离线预检和本地 HTTP 实测；真实服务的鉴权、模型可用性、限流和账单尚未验证，配置及执行方式见 `docs/experiment/api_handoff.md`。请求次数与输出 token 上限不等于金额硬封顶。
