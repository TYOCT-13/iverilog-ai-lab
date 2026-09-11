---
name: 缺陷报告 / Bug report
about: 报告工具本身的问题（不是被测设计的功能缺陷）
title: "[Bug] "
labels: ["bug"]
---

<!--
先确认一件事：如果你看到的是"某个设计的某条检查失败"，那通常是**工具的预期输出**，
不是工具的 Bug。基准集里 78 个缺陷就是为此准备的。
真正属于本仓库 Bug 的例子：命令行报错、报告渲染异常、路径策略误判、CI 失败、
同一输入两次运行结果不一致。
-->

## 环境

- 操作系统与版本：
- Python 版本：`python -V`
- Icarus Verilog 版本：`iverilog -V` 首行
- Yosys 版本（若涉及综合层）：
- 本仓库提交号：`git rev-parse --short HEAD`
- 工具探测结果：`python -c "from iverilog_ai.core.toolchain import locate_tools, describe_tools; print(describe_tools(locate_tools()))"`

## 复现步骤

```powershell
# 请贴出可直接复制的命令
```

## 实际结果

```
（粘贴输出；如果是报告或页面问题，请附截图）
```

## 期望结果

## 是否可稳定复现

- [ ] 每次都复现
- [ ] 偶发（请描述概率与条件）

## 补充信息

- 如果问题与"结论是否正确"有关，请附上：用例名、`run` 目录下的 `result.json`，
  以及该次运行的编译/仿真日志。
- **请勿粘贴 API 密钥**。需要提供凭据相关的信息时，只描述变量名与是否设置。
