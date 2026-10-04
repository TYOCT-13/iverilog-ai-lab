# ICARUS 本地证据包与复核入口

日期：2026-10-04。本轮已生成本地 ZIP，保留真实结果和原始失败。它不代表已完成真人试用、独立人工审核、异机复现或正式参赛提交。

## 1. 已生成的文件

| 项目 | 实际记录 |
|---|---|
| ZIP | `.iverilog-ai/ic-evidence-pack-20261004.zip`，86,376,627 字节，约 86.4 MB / 82.4 MiB |
| 解包目录 | `.iverilog-ai/ic-evidence-pack-20261004/` |
| 文件数 | 41,007，包含 manifest；其中 41,006 项有逐文件 SHA-256 |
| 源码快照 | 6 份 Git 提交归档 |
| 材料提交 | `81114bce3f3bb72e2e2a05969b15200c1a4ae767` |
| 最终测试源码 | `867b8bd564c881954c98cc18813884a4074d1ed5`：914 通过 / 1 跳过 / 0 失败 |
| 注册输入 | 四份快照共 424 份，逐项匹配原登记哈希，包含跨快照重复文件 |
| 凭据检查 | 按指定 API 密钥的正文值扫描，未发现；未打包本机 API 配置或密钥文件 |

ZIP 的 SHA-256：

```text
1d91d09309f45e978cddbb5001bbde022cfc4fbb03b414c7e78346b14a9bf15f
```

机器回执见 [evidence_pack_2026-10-04.json](evidence_pack_2026-10-04.json)。包内 `manifest.json` 记录每个文件的路径、字节数、SHA-256、对应提交或原件路径。清单不将自身纳入自身哈希；包外回执另存清单和整包哈希。

## 2. 收录范围

- 历史手写基准、消融、离线与真实在线策略、管线及综合矩阵的完整原始目录。历史 `83/83`、`61/67` 不改写成新 Agent 成绩。
- 单模块 3 次 API 接线记录、有效五策略 pilot 的全部 60 行，以及首次中断记录。失败、截断、不可判定和未开始样本均保留。
- 三个冻结外部 RTL、24 输入重放、有限规格测试、真实 UART RX API 联调、已保存计划的离线变体重放，以及旧采样问题记录。
- 22 项机器验收、浏览器三尺寸截图、四次完整回归日志。pytest 临时测试工作区未收录。
- 四份原登记输入快照与其子清单，以及对应的六份完整源码归档；最新材料中有 IC 报告、试用任务卡、人工复核空表与录制指南。

仅使用明确的目录白名单，没有打包整个用户目录或整个 `.iverilog-ai/`。本包用于本地技术复核，其中保留了本机路径；正式提交材料的匿名检查另行完成。历史矩阵当时没有登记的源码冻结或费用信息没有事后补造。

## 3. 源码与原冻结字节的区别

`source/` 是 Git 按仓库归档属性导出的文件。普通文本采用仓库规范换行，`.cmd`、`.ps1` 则按属性导出为 CRLF；不能声称归档中所有文件都与 Git blob 逐字节相同，也不能将归档字节直接当成原 Windows 实验字节。

`raw/frozen-registered-inputs-20261004/` 分别登记：有效 pilot 64 份、首次中断 64 份、采样保护验证 148 份、最终 PDF 后验证 148 份。4 份通过 LF→CRLF 恢复后精确匹配，获取方法、原哈希、Git 规范字节哈希均有记录。

复放历史试验时，先提取**该试验对应提交**的完整源码，再用对应子快照的 `files/` 按相对路径覆盖登记文件。不要用最新源码替代旧版并继续引用原成绩。原 pilot 冻结于 `e9b7b8a`；后续采样保护没有重跑它。

## 4. 先核对包，再操作

在本项目根目录执行以下只读检查，不会发送 API 请求：

```powershell
@'
from pathlib import Path
import hashlib, json, zipfile
p = Path('.iverilog-ai/ic-evidence-pack-20261004.zip')
r = json.loads(Path('docs/competition/ic/evidence_pack_2026-10-04.json').read_text(encoding='utf-8'))
assert hashlib.sha256(p.read_bytes()).hexdigest() == r['zip_sha256']
with zipfile.ZipFile(p) as z:
    assert z.testzip() is None
    m = json.loads(z.read('manifest.json'))
    assert hashlib.sha256(z.read('manifest.json')).hexdigest() == r['manifest_sha256']
    expected = {e['path'] for e in m['files']} | {'manifest.json'}
    assert len(z.namelist()) == len(expected) == r['files_including_manifest']
    assert set(z.namelist()) == expected
    for e in m['files']:
        assert hashlib.sha256(z.read(e['path'])).hexdigest() == e['sha256'], e['path']
print('文件集合、CRC、整包及全部逐文件 SHA-256 一致')
'@ | python -X utf8 -
```

解压到新目录，原始包保持只读。在新目录中的 `source/` 选择材料提交 `81114bce…` 的 ZIP，解压为 `workspace/`。Python 3.11+、项目依赖和 Icarus 的安装步骤见 [复核指南](../../reproduce_in_10_minutes.md)。已有依赖时，下面的外部样例可以离线运行；首次安装依赖仍可能需要联网。

在 `workspace/` 内运行，原件位于同级 `raw/`，输出选择尚不存在的新目录：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python scripts/run_external_verification_agent.py `
  --manifest ../raw/external/frozen-20261004-ic/manifest.json `
  --candidate ../raw/external/frozen-20261004-ic/uart_rx.v `
  --module uart_rx --output-dir .iverilog-ai/pack-offline-check `
  --iverilog iverilog --vvp vvp
```

该样例没有 `--execute`，不调用模型。候选与基线相同，预期有限资格检查通过，输出 `compared_samples=547`、`differences=0`，断言 `checks/failures=0`。这是限定输出的行为比较，不是完整功能证明。真实 API 重跑需要自备凭据、明确预算和新输出目录，会产生费用；原服务商账单不在包内。

## 5. 本轮核验与尚未完成的部分

构建时实际核对 ZIP CRC、文件集合与逐文件哈希，并核对当前 148 份源码仍与最终回归登记相符。[包后代理审计](../../review/ic_pack_review_2026-10-04.md)另行重算，不把内部作者关系写成独立人工审核。

此外已从**外层 ZIP**提取材料版源码和四个冻结外部输入文件，显式将 Python 导入路径指向提取后的 `src/`，用本机已有依赖和 Icarus 实际执行离线 UART RX：退出 0、547 项输出比较、0 差异、0 API 请求。公开记录见 [smoke.json](../../experiment/ic-pack-smoke-2026-10-04/smoke.json)、[stdout](../../experiment/ic-pack-smoke-2026-10-04/stdout.log)、[stderr](../../experiment/ic-pack-smoke-2026-10-04/stderr.log)。首次辅助脚本查错字段导致 KeyError，应用已正常退出；错误与原输出保留，修正后检查原字段，没有将辅助脚本错误改写成应用成功率。

这个检查没有新建干净机器，未重跑付费 pilot，也不证明整个矩阵已在异机复现。真人试用、独立人审、答辩 PDF、视频、报名及正式提交仍按 [差距清单](gap_checklist.md)执行。

本页、包后审计和离线抽检记录在 ZIP 冻结后产生，存于包外并另行提交本地 Git。包内材料提交仍为 `81114bce…`，不为加入这些后验回执重新覆盖原 ZIP。
