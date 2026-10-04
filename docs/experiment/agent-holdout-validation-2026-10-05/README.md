# 新模块评测前全仓验证

2026-10-05，冻结源码前对当前候选工作字节运行完整 pytest 和 src/ui/scripts mypy。1570 passed、2 skipped、0 failed，mypy 83 源码 0 error；全部源码/测试/资产前后指纹相同。API 请求为 0。两跳过为 Windows 目录符号链接权限和当前为空的推荐断言表。

实际使用仓库外全新系统临时目录；原始日志、XML、命令、各文件指纹与耗时见 [r1回执](r1/receipt.json)。此全仓数已包含专项，不与520/28/22或其他重叠测试相加。不是外部 Actions、独立干净checkout、真人试用或H02。
