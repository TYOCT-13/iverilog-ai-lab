# 给开源项目做行为回归：`verify-diff` 与 GitHub Action

面向：**收到一个重写模块的 PR、但项目里根本没有 testbench 的维护者**，以及**想让 AI 重写
自己的 RTL 后确认行为没变的人**。

---

## 1. 它解决什么问题

上游 RTL 项目普遍没有 testbench。于是：

- 有人提了一个"只是重构"的 PR——你没法快速判断行为有没有变；
- 你想用 AI 把某个模块改写得更清楚——改完只能自己盯着看；
- 项目有一堆陈旧模块——你想知道哪些还能用，但为每个模块补 TB 不现实。

**本工具不需要被测项目自带 testbench。** 它从 RTL 的 `module` 头自动提取 DUT 合约草稿，
用离线确定性规划器按合约生成测试计划，然后把**同一份**测试计划喂给两份 RTL，
逐检查项与逐拍波形比对。

```
基线 RTL ─┐
          ├─→ 同一份测试计划 → 两次真实 Icarus 仿真 → 逐项 + 逐拍比对 → 结论
候选 RTL ─┘
```

## 2. 命令行用法

```bash
# 最少只要两个文件
iverilog-ai verify-diff --baseline rtl/old.v --candidate rtl/new.v

# 想更可信：提供确认过的合约与测试计划
iverilog-ai verify-diff \
  --baseline rtl/old.v --candidate rtl/new.v \
  --contract examples/old_contract.json \
  --plan plan.json

# 打印可贴进 PR 的 Markdown 报告
iverilog-ai verify-diff --baseline rtl/old.v --candidate rtl/new.v --print-markdown
```

**退出码**（CI 依赖它）：

| 码 | 含义 | 该怎么处理 |
|---:|---|---|
| `0` | 两侧一致 | 可以合并 |
| `1` | 两侧不同 | 要看差异清单 |
| `2` | 未取得可比证据 | **不要当成通过**：可能是合约/计划没准备出来、波形没比成、或测试计划没产生带期望值的检查项 |

> **`2` 千万别当成 `0`。** 这是本工具最容易被人为放宽的一点：把"没测出问题"当成"没问题"，
> 正是它想避免的事。

## 3. GitHub Action 用法

以下使用真实仓库地址。2026-10-08建仓时远程仍为空，须先上传代码再调用；外部调用尚未实际验证，见[建仓记录](../competition/repository_readiness_2026-10-08.md)。

在仓库里新建 `.github/workflows/behavior-diff.yml`：

```yaml
name: 行为回归

on:
  pull_request:
    paths:
      - "rtl/**/*.v"
      - "rtl/**/*.sv"

jobs:
  verify-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: 取得基线版本（PR 的目标分支）
        run: |
          git show origin/${{ github.base_ref }}:rtl/module.v > /tmp/baseline.v

      - uses: TYOCT-13/iverilog-ai-lab@main
        with:
          baseline: /tmp/baseline.v
          candidate: rtl/module.v
          # 以下都可省略：
          # contract: examples/module_contract.json
          # plan: plan.json
          # module: module
          # workdir: .
          # output-dir: .iverilog-ai/verify-diff
          # python-version: "3.11"
          # comment-on-pr: "false"
```

跑完在 **Job Summary** 里直接看到那份对比报告（结论、凭什么这么说、差异清单、这次没覆盖到什么），
同时在 Artifacts 里拿到 `verify-diff-report`。

### 让结论自动出现在 PR 对话里

```yaml
    permissions:
      contents: read
      pull-requests: write        # 只有开了这个开关才需要
    steps:
      - uses: TYOCT-13/iverilog-ai-lab@main
        with:
          baseline: /tmp/baseline.v
          candidate: rtl/module.v
          comment-on-pr: "true"
```

行为约定：

- **原地更新**：评论带一个固定标记（`<!-- iverilog-ai-verify-diff -->`），重跑时会找到自己
  上一条评论改内容，**不是每跑一次刷一条**；
- **权限不足只警告**：没有 `pull-requests: write` 时 `gh` 会失败，但这一步是
  `continue-on-error`，不会把构建弄红——结论本来就在 Job Summary 和 Artifacts 里；
- **没产出报告就不评论**：对比连报告都没跑出来时跳过，并留一条 `::warning::`。

### 输入

| 名称 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `baseline` | ✅ | — | 基线 RTL 路径（相对 `workdir`） |
| `candidate` | ✅ | — | 候选 RTL 路径（PR 里改写后的版本） |
| `contract` | | 空 | DUT 合约 JSON；留空则从基线 RTL 自动提取**草稿** |
| `plan` | | 空 | 测试计划 JSON；留空则用离线确定性规划器生成 |
| `module` | | 空 | 模块名；留空则用合约里的 `module` |
| `workdir` | | `.` | 运行目录（通常是仓库根） |
| `python-version` | | `3.11` | Python 版本 |
| `output-dir` | | `.iverilog-ai/verify-diff` | 工件目录 |
| `comment-on-pr` | | `false` | 把结论评论到 PR。需要调用方授予 `pull-requests: write`；**未授予时只警告、不让构建变红** |

### 输出

| 名称 | 说明 |
|---|---|
| `status` | `identical` / `different` / `inconclusive` |
| `status-label` | 中文结论（两侧一致 / 两侧不同 / 未取得可比证据） |
| `exit-code` | `0` / `1` / `2` |
| `report-path` | 可贴进 PR 的 Markdown 报告路径 |

## 4. 结论凭什么可信（读之前先看这一段）

- **裁决只来自两次真实 Icarus 仿真**：同一份测试计划、同一份合约，任何检查项或任何 DUT
  可观测信号不同即判"不同"。
- **合约草稿会削弱灵敏度，但不影响"不同"的可信度**：自动提取的合约里，端口与位宽通常可信，
  复位极性与同步/异步是猜的。两侧跑在同一套（可能不精确的）测试台下，所以
  「两侧不同」永远可信，而「两侧一致」的覆盖范围可能因此变窄。报告里会标注这一点。
- **没有可比证据就不说"一致"**：如果测试计划没产生带期望值的检查项、波形又没比对成功，
  结论是 `未取得可比证据`（退出码 2），而不是 `一致`。
- **它不判断哪一边是"对的"**：只说"两份实现是否一致"。哪一份符合规格，仍由规格与人工判断。

## 5. 已知边界

- 候选文件里必须定义**与基线同名**的模块（测试台按合约里的模块名例化）；
- 不做时序签核、形式化等价证明、代码覆盖率；
- 波形比对有采样上限，超出会在报告里标注"波形记录被截断"；
- 只覆盖测试计划激励范围**之内**的行为一致——范围之外的一致它证明不了，报告里也这么写。
