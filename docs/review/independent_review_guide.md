# 外部模块与人工变体的独立复核指南

目的不是让审核人给项目背书，而是确认“这些输入是什么、改动是否真的改变功能、工具结论能否从证据推出”。本流程不会自动产生“独立审核通过”的证明。

## 1. 谁来审核，如何说明关系

审核人应有 Verilog / RTL、testbench、时钟复位和基本波形阅读经验。优先选择未参与本项目开发的人；最低应没有编写被审核功能、变体、测试计划或判据。记录其与团队的关系，例如同学、指导老师、同组但未参与该部分、完全外部同行，以及是否接受报酬。

同团队非作者可以做技术复核，但要如实披露，不能写成外部机构认证。审核人不必是竞赛评委，也不必公开真实姓名；可以在公开材料中使用代号，原始身份与确认记录由团队经同意留存。

开发者解释、AI 辅助阅读和代理自测可以帮助定位文件，不能代替真人的语义判断或签署。审核人如使用 AI，应记录工具、用途及自己核查了哪些部分。

## 2. 本次到底审什么

当前注册表在 `scripts/check_external_module.py` 的 `MODULES`；历史结果见 `docs/experiment/external_results.md`。共有 3 个模块，每个模块有 1 个基线、5 个功能变体、1 个拟等价改写、1 个编译失败输入，即 **3 个基线检查 + 21 条候选检查**。只有全量复核并记录才能说“这 21 条均已复核”；抽查必须写明抽查范围。

| 模块 | 来源及范围 | 必须关注的语义 |
|---|---|---|
| `uart_rx` | `alexforencich/verilog-uart`；未参与本项目规则调参，但与开发集来源同作者 | 高有效同步复位、LSB 位序、停止位错误、valid/ready、非回文测试字节 |
| `uart_tx` | 同一 UART 仓库，不能当成另一个独立来源 | 位周期、停止位、busy 清除、发送数据；环回成功可能掩盖一拍时序误差 |
| `priority_encoder` | `alexforencich/verilog-axi`，属于开发集预检样例，不是外部留出集 | 参数位宽、优先方向、空输入 valid、编码值与独热输出 |

历史记录包含调试后补充激励的过程，不能改写成从未看过结果的盲测。若审核人尚未看历史判定，可先只发规格、源文件、差异和中性编号，在其写下预测后再开放工具结果；若已经看过报告，就记录“知晓既有结论的复核”。盲的是预期类别或工具结果，不是剥夺审核所需的规格和源码。

## 3. 先冻结输入，再交付

准备一个只读留存副本和一个可执行副本，给本次复核分配代号。至少保留：

- 当前代码 commit；若工作区有修改，另附实际修改和文件哈希，不能仅用 commit 声称可复现。
- `.iverilog-ai/external/manifest.json` 及上游许可；若缺 commit，明确以哪些文件 SHA-256 固定，不能补造版本号。
- `.iverilog-ai/external/uart_rx_check/` 中本轮 3 模块的 baseline、候选、contract、plan、`tb_<module>_baseline.v`、`evidence.json` 和已有比较产物。
- `uart_tx` 规格测试的接收端依赖，以及 `scripts/check_external_module.py`。
- Python、Icarus 版本、操作系统、完整复现命令；每条新运行放在独立输出目录。

从仓库根目录检查版本和输入哈希，例如：

```powershell
git rev-parse HEAD
git status --short
python -V
iverilog -V
Get-FileHash .iverilog-ai/external/uart_rx_check/uart_rx_baseline.v -Algorithm SHA256
Get-FileHash .iverilog-ai/external/uart_rx_check/uart_rx_mut_bit_order.v -Algorithm SHA256
```

这些命令只用于核查，不把命令输出预先当作审核结论。核对交付清单后再运行。路径缺失就记录缺失并请团队补包，不用另抓最新上游来替换冻结版本。

**现有脚本限制**：`fetch_external_modules.py` 当前抓取的是 `common_cells`，并不能自动补齐这里的 3 个模块。`check_external_module.py` 无命令行参数解析，硬编码本机 `D:\iverilog\bin` 工具路径及输入路径，会在固定目录重写变体和产物；不要对冻结证据运行它，也不要把 `--help` 当安全预览。需要整套重建时，在副本中由团队先解释这些限制。审核人逐项重放可使用下面已存在的 CLI。

## 4. 审核顺序

### A. 先核对基线与规格测试台

读端口、参数、时钟边沿、复位极性/同步性、有效数据条件和协议边界。把每条核心规格映射到测试台检查，确认期望值由规格导出，而不是直接复制 DUT 的计算结果。

现有规格测试台是与 `verify-diff` 分开的判据，仍由项目开发者提供；“独立的测试方式”不等于“独立真人编写或审核”。基线测试通过只支持被检查条件，不能证明基线对所有输入正确。

特别核对：UART 测试用 `0x96` 等非回文位序；坏停止位确实被驱动；复位期间/解除后的采样没有竞争。发送侧环回测试历史上漏掉位周期少一拍与 busy 不清，需要另看这些信号的时序，不能只看收到的字节。优先编码器需要核对两种优先方向的参数配置。

### B. 逐条看差异与最小触发证据

对 15 个功能变体，每条写下：修改位置、修改前后的语义、哪条规格可能受损、触发输入/状态、最早能观察到差异的拍数和输出。保留源文件差异，不只引用变体名字或工具的红色提示。

先使用已有计划定位触发片段。可记录“从原计划截取的触发窗口”，但若没有实际重跑缩减计划，不得称其为“经验证的最小反例”。需要补充激励时，保留旧计划和结果，另存新计划、理由及新运行，不把补测覆盖成原先就成功。

对 3 个拟等价改写，检查改写是否在已声明参数、位宽、复位和可达状态范围内成立；`identical` 只表示当前有限激励未观察到差异，**不是形式等价证明**。若只能确认有限测试一致，就只记录这层结论。

对 3 个编译失败输入，查编译器退出码和错误位置；应归为“缺少可比行为证据”，不能算功能缺陷检出。源码语法错误和工具安装/路径错误也要区分。

### C. 重放并保存逐条原始记录

在可执行副本的仓库根目录，选择一个从未使用的复核目录。工具不在 PATH 时，将 `iverilog` / `vvp` 替换为本机可执行文件路径；`verify-diff` 可加 `--iverilog`、`--vvp`，无需修改业务源码。

```powershell
$reviewDir = '.iverilog-ai/independent-review/reviewer01-session01'
$evidenceDir = '.iverilog-ai/external/uart_rx_check'
if (Test-Path -LiteralPath $reviewDir) { throw '请换一个新的复核目录，保留旧记录。' }
New-Item -ItemType Directory -Path $reviewDir | Out-Null

# 规格测试：只编译基线和该测试台。
iverilog -g2012 -s tb_uart_rx -o "$reviewDir/rx_baseline.vvp" "$evidenceDir/uart_rx_baseline.v" "$evidenceDir/tb_uart_rx_baseline.v" 1> "$reviewDir/compile.stdout.txt" 2> "$reviewDir/compile.stderr.txt"
$compileExit = $LASTEXITCODE
$compileExit | Set-Content "$reviewDir/compile.exit.txt"
if ($compileExit -eq 0) {
    vvp "$reviewDir/rx_baseline.vvp" 1> "$reviewDir/spec.stdout.txt" 2> "$reviewDir/spec.stderr.txt"
    $LASTEXITCODE | Set-Content "$reviewDir/spec.exit.txt"
}

# 逐条对比：显式使用冻结合约和计划，不自动换成新的激励。
python -m iverilog_ai verify-diff --baseline "$evidenceDir/uart_rx_baseline.v" --candidate "$evidenceDir/uart_rx_mut_bit_order.v" --module uart_rx --contract "$evidenceDir/uart_rx_contract.json" --plan "$evidenceDir/uart_rx_plan.json" --output-dir "$reviewDir/rx-mut-bit-order" --print-json 1> "$reviewDir/compare.stdout.txt" 2> "$reviewDir/compare.stderr.txt"
$LASTEXITCODE | Set-Content "$reviewDir/compare.exit.txt"
```

对其他输入，更换 candidate 和全新的输出目录。`uart_tx` 规格编译还需接收端，例如冻结包中的 `uart_rx_baseline.v`；`priority_encoder` 使用自己的 `tb_priority_encoder_baseline.v` 和 `tb_priority_encoder` 顶层。不把一次 UART 重放写成 3 个模块全部复核。`verify-diff` 的非零退出码可能是检出了差异，必须结合结构化 `status`、差异与日志判断，不能仅看退出码叫“程序崩溃”。

## 5. 如何给每条结论

审核结论与工具 `identical/different/inconclusive` 是两套字段，不混用：

| 审核结论 | 何时填写 |
|---|---|
| `confirmed` | 该条**具体、有限的主张**有源码、规格和运行证据支持；注明到底确认了什么 |
| `disputed` | 有相反证据，或变体并未造成宣称的语义变化；留下争议与反例 |
| `inconclusive` | 缺文件、环境不能重放、证据不足或语义尚不清楚；写明缺口 |
| `out_of_scope` | 没有审核该模块/参数/判据，或超出审核人的能力与约定范围；不能计作通过 |

例如，编译失败输入可以有工具结论 `inconclusive`、审核结论 `confirmed`，意思是“确认工具正确拒绝给出功能一致性结论”，不是确认设计正确。拟等价改写可以确认“本计划未观察到差异”，但对“全输入等价”仍是 `out_of_scope`。

每个基线及候选复制一条 [JSON 模板](variant_review_template.json)中的记录；没做的也记录，不能只保留成功项。汇总写实际审核人数、独立关系、完成数量、各类结论数量、争议和未覆盖范围。修改后重审新增记录并链接旧记录，不覆盖原始意见。

审核人最后亲自确认 [整次记录](review_record_template.md) 的日期、范围和原话。团队可以整理排版，但须保留原始回答及修改轨迹，经本人核对再引用；不得由代理生成姓名或替其确认。
