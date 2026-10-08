# GitHub 自动检查修复（2026-10-08）

远端 main 已接收 `e14e7eddf525c0d74feab508ebfe4659700a959f`，实时 `git ls-remote --heads origin main` 与本地提交一致。用户收到的是该提交触发的 Actions 失败邮件；代码上传与上传后自动检查是两个不同结果。

## 原始失败

| 检查 | 实际失败原因 | GitHub 原始任务 |
|---|---|---|
| verify / test | 只安装核心包，执行单测时报 `No module named pytest` | [verify 日志](https://github.com/TYOCT-13/iverilog-ai-lab/actions/runs/37743913232/job/113200778295) |
| CI / Linux Python 3.12 | 编码门禁发现已冻结的 `attempt-1-incomplete.json` 中原有乱码；Python 3.11 同样停在该门禁 | [Linux 日志](https://github.com/TYOCT-13/iverilog-ai-lab/actions/runs/37743913305/job/113200779362) |
| CI / Windows Python 3.12 | Chocolatey 已成功安装 Icarus 11.0.0 到 `C:\ProgramData\chocolatey\lib\iverilog\tools`，脚本却只搜索 `C:\iverilog*`，最终报未找到工具；Python 3.11 同样失败 | [Windows 日志](https://github.com/TYOCT-13/iverilog-ai-lab/actions/runs/37743913305/job/113200779007) |

原始服务端日志已读取并保存在本机 `.iverilog-ai/ci-audit-20261008/original-e14e7ed/`，未作为可克隆材料上传。以下 SHA256 绑定本机下载原件，GitHub 上的任务链接是公开交接入口：

| 原件 | SHA256 |
|---|---|
| verify-test.log | `c33580542c2a298562e275528b92e07b1d216102083cbd1710deba64205c95d3` |
| ci-linux312.log | `a7a6b5b7eb462bbdeda9e9aa3c4497937d78dc9e36cbb5f24bfd3080cf695ac0` |
| ci-windows312.log | `62013067edda13f5bece0563fd9bb20127eae36ffc1e716dc642bbddb3e9f3c3` |

## 修复

- 两套工作流使用 uv 0.9.9，按现有 `uv.lock` 安装 dev 和 ui 依赖，所有检查由 `uv run --no-sync` 在该环境执行。修复缺少 pytest、UI/渲染依赖遗漏，以及绕开锁文件安装最新版 mypy 的问题。锁文件和核心业务不改写。
- CI 的综合工具单独固定为 yowasp-yosys 0.69.0.0.post1233、yowasp-runtime 1.96、wasmtime 47.0.1，与本次作者本机及原始 Linux 任务中实际探测的版本一致。
- Windows 使用 Icarus 12.2022.06.11 固定安装包、SHA256 校验、静默安装和明确的 bin 路径；验证编译器与 vvp 后写入 GITHUB_ENV/GITHUB_PATH。该安装步骤上限 5 分钟，避免递归遍历整个系统盘。安装包哈希来源：[Microsoft WinGet 固定版本清单](https://github.com/microsoft/winget-pkgs/blob/master/manifests/i/Icarus/Verilog/12.2022.06.11/Icarus.Verilog.installer.yaml)。
- 编码检查只登记一份历史失败回执的精确路径及 Git LF SHA256，保留其原有乱码；计算时兼容 Windows CRLF，不写回文件。回执删除、内容修改、BOM 错误仍失败，其余文件继续执行全部编码检查。新增回归覆盖 LF/CRLF 保留、内容变化、删除和未登记乱码。

历史回执 Git LF SHA256 为 `c1f03f9288b99aaf73c720bab43ae9b41b2092bf8d0b8666456b1c00840e995f`，作者现有 CRLF 原件 SHA256 为 `e59484658abf71f2bf91e60f8b6105d57f92468135bf03a12aaf467af97b0b58`，本轮均已再次核对，未改原件。

## 作者本机验收

- 第一次全量检查：2046 passed / 2 skipped / 1 failed，311.64 秒。作者将 pytest 临时目录设在仓库内，导致“产物目录在仓库外时应拒绝”的测试前提不成立。该次失败日志保留，没有修改被测保护逻辑或该测试。
- 第二次全量检查：临时目录位于系统 Temp，2047 passed / 2 skipped / 0 failed，330.71 秒。两个跳过分别为本机缺少目录符号链接权限、现有推荐断言表为空。
- mypy：88 源文件无错误；编码门禁 0 问题；AST 未可达检查 294 文件无问题；两份工作流 YAML 可解析，Windows 安装脚本 PowerShell 解析错误 0。
- uv 锁依赖 dry-run：解析 53 包，成功；该项是解析检查，没有创建新环境。本机全量回归使用已有验收环境并将 PYTHONPATH 指向本次项目源码，不声称是另一台机器首次安装。

本机两次完整日志分别保存在 `.iverilog-ai/ci-audit-20261008/local-validation-v1/pytest.log` 和 `local-validation-v2/pytest.log`。不合并两次测试数，也不把本机回归称为真人复现、H02 或新模型效果实验。

## 外部结果边界

本文随修复提交，修复后的 Actions 需在推送后由 GitHub 实际执行。本机通过不预先写成 GitHub 全部通过；后续以该修复提交对应的工作流结果为准，原始 e14e7ed 失败记录继续保留。

本轮未运行新的 DeepSeek 模型实验，不更改已冻结的对照结果、API 账本或 v3 参赛材料。真人异机完整复现、独立 H02 和外部仓库调用 composite Action 仍各自需要真实证据；本仓库自身的 CI 不等于外部 Action 调用。

## 第二轮：实际 runner 中继续发现的问题

首轮修复 `8a2997e` 已推送，两套工作流真实执行，并已越过安装与编码门禁。随后全量测试暴露出旧的跨平台和环境假设，原始结果按该提交保留：

| 任务 | 实际完整结果 | 原始任务 |
|---|---|---|
| verify / Linux Python 3.12 | 9 failed / 1911 passed / 105 skipped / 24 errors，109.40 秒 | [任务](https://github.com/TYOCT-13/iverilog-ai-lab/actions/runs/37746979871/job/113210676484) |
| CI / Linux Python 3.12 | 10 failed / 1914 passed / 101 skipped / 24 errors，127.78 秒 | [任务](https://github.com/TYOCT-13/iverilog-ai-lab/actions/runs/37746979928/job/113210676924) |
| CI / Windows Python 3.12 | 10 failed / 1917 passed / 98 skipped / 24 errors，158.82 秒 | [任务](https://github.com/TYOCT-13/iverilog-ai-lab/actions/runs/37746979928/job/113210677043) |

对应下载原件位于本机 `.iverilog-ai/ci-audit-20261008/fix-8a2997e/`，SHA256 分别为 verify `2872aa74e6704669d9eb36886f14ff5d47eb7ec053d6bbee3c06f1d929415f62`、Linux `f6fd68b385192c042e89e4928cbd26d1b1d1ec48d020e7abaa01606977a591cf`、Windows `3eb65b58f4af7320dd360e6056c4c67f2060cefbe6f5ac830791cdd724abf1ac`。

第二轮修复内容：

- Checkout 获取完整历史，供测试读取 b9f7a6e、f664d85、a969337 的原始 Git blob；不改写那些冻结源码，也不跳过历史完整性校验。
- 两份工作流显式开启 Python UTF-8 模式，避免 Windows 默认 cp1252 把 UTF-8 轨迹读坏。
- 注册路径使用 PureWindowsPath 识别 Windows 盘符、根路径和回退路径，在 Linux 上也必须先拒绝再读文件。辅助执行器是向前维护的新版，旧批次原件和旧 Git 提交保持不变，不把旧模型效果成绩归到新版。
- CLI 越界测试使用 pytest 的仓库外临时目录，避免 Linux 未设置 TEMP 时错误地把“越界”文件写入仓库内。
- 真实仿真测试统一调用现有工具探测，移除作者 D 盘作为实际工具可用性的判断，不因盘符不同静默少测。
- Linux CI 使用系统原生 Yosys，Windows 保留已固定的 yowasp 版本；工具实际路径继续打印并核验。
- 旧报告是使用作者 Windows 字体生成的材料，Linux 内置字体的字形映射与分页文本位置不能充当 PDF 过期判据。新增[源与 PDF 字节绑定](report_pdf_source_bindings_2026-10-08.json)，来源是本次首轮作者完整回归中实际通过的两组逐页重渲染比较。每个平台都必须验证源 LF SHA256 与 PDF 原件 SHA256；相同字体时继续重渲染逐页比较，字体不同时只声明字节绑定与 PDF 可读取，不声明布局相同。新增负向回归确认字体差异不能掩盖源或 PDF 的改变。原 PDF 和源文件不改写。

第二轮作者全量检查保留为 `local-validation-v3/pytest.log`：2049 passed / 2 skipped / 2 failed，331.12 秒。两项失败来自新增测试夹具把 CRLF 原文哈希误填为 LF 哈希，绑定检查正常拒绝；修正该夹具的 LF 计算后，PDF、UI Agent 和外部适配器三文件定向检查共 39 passed，31.72 秒，原失败记录不覆盖。mypy 88 文件无错误、编码门禁 0 问题、AST 294 文件无问题、两份工作流解析和配置核对通过。两次测试不相加作完整回归成绩，第二轮完整外部结果仍需以新提交的 GitHub 任务为准。
