# GitHub建仓与本地引用核对（2026-10-08）

提交者提供的真实仓库为[TYOCT-13/iverilog-ai-lab](https://github.com/TYOCT-13/iverilog-ai-lab)，Git地址为 https://github.com/TYOCT-13/iverilog-ai-lab.git 。本次更新引用、README、复现说明和当前待办，没有推送代码或创建线上工作流运行。

## 实际状态

- 本地main为7ee7231，工作目录原先干净，origin的fetch/push地址已指向上述仓库。
- `git ls-remote`实际退出0、输出为空；未登录公开网页显示空仓库。可确认仓库已创建并公开可访问，不能据此确认任何源码已经上传。
- GitHub REST API匿名元数据请求受速率限制，返回限流错误；公开访问判断来自上述网页及Git读取，不使用失败的API请求作证明。
- `CITATION.cff`已换成真实仓库地址，Action文档中的调用方地址已同步。外部Actions、远程下载、另一台设备运行及真人/H02仍未完成。

本地检查及源文件绑定见[核对回执](repository-readiness-2026-10-08/receipt.json)。历史实验、材料和失败记录继续按各自版本引用，本次不产生新的模型API请求或DUT运行。

## 本地检查

- 仓库占位检查：59个交付面文本，0占位、0错误、0警告。原先引用地址造成的门禁错误已消除，不覆盖历史1 error回执。
- 本轮材料补登记后的索引检查另存回执的closure_checks；早先292/292属于补登记前的检查，不与后续检查相加。
- YAML解析确认引用字段等于真实仓库地址；业务源码、测试、RTL、锁文件与v3正式材料相对7ee7231无改动。
- 首次辅助记录工具因GBK标准输出编码失败；[未完成回执](repository-readiness-2026-10-08/attempt-1-incomplete.json)保留。该次文字捕获未强制子进程编码，文字可能受替换解码影响；后续明确UTF-8后完整重检，结论使用新捕获。

## 下一步上传

完成本地引用提交后，在项目目录执行：

```powershell
git push -u origin main
```

本次没有执行该命令。上传后须核对远程main的实际提交，再从新目录克隆并按[当前复核指南](../reproduce_current.md)运行；克隆和异机验证分别登记。参赛系统上传、团队编号与分享回执也分别核实。
