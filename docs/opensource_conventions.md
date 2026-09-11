# 从开源项目实测的编码与验证约定

生成时间：2026-09-11T00:46:54.579673Z
生成方式：`python scripts/ingest_open_source_conventions.py`（对固定提交的源码做统计度量）

## 这份东西是什么，不是什么

**是**：对真实开源 Verilog 项目的**统计度量**——上游有多少比例的文件采用了某种写法。
产物只含聚合数字与每文件的 sha256 指纹，**不含任何上游源代码**。

**不是**：不是规范、不是 lint 规则、不参与 PASS/FAIL 判决。
它唯一的作用是给 AI 规划器提供社区惯例背景，让生成的测试计划更贴合真实工程写法。
覆盖率不足的探针会被标成 `weak`，措辞明确写成「上游较少如此，不构成约定」。

## 度量来源

| 项目 | 固定提交 | 许可证 | 度量文件数 | 源码字节 | 说明 |
|---|---|---|---:|---:|---|
| [alexforencich/verilog-axi](https://github.com/alexforencich/verilog-axi) | `516bd5dadc33` | MIT | 83 | 1093135 | AXI 接口、FIFO 与握手实现，工程化程度高 |
| [ZipCPU/wb2axip](https://github.com/ZipCPU/wb2axip) | `2e8d3bc2d26d` | GPL-3.0-or-later | 89 | 1909729 | 总线与握手参考实现；GPL 项目——本模块只读取统计量、不复制代码 |

## 实测统计

### alexforencich/verilog-axi

| 探针 | 命中/总数 | 覆盖率 | 置信度 |
|---|---:|---:|---|
| 文件声明了 `timescale | 83/83 | 100% | `strong` |
| 模块使用 ANSI 风格端口列表 | 55/55 | 100% | `strong` |
| always 块以时钟边沿为敏感条件 | 125/125 | 100% | `strong` |
| 时序块内出现过非阻塞赋值 <=（宽口径） | 125/125 | 100% | `strong` |
| 时序块没有阻塞赋值（for 循环变量除外） | 120/125 | 96% | `strong` |
| 时序块敏感列表含复位边沿（异步复位） | 3/125 | 2% | `weak` |
| 低有效复位命名为 xxx_n | 0/147 | 0% | `weak` |
| case 语句带 default 分支 | 0/35 | 0% | `weak` |
| 使用参数/localparam 表示状态或常量 | 83/83 | 100% | `strong` |
| 端口声明显式写出位宽 | 1448/2243 | 65% | `moderate` |

### ZipCPU/wb2axip

| 探针 | 命中/总数 | 覆盖率 | 置信度 |
|---|---:|---:|---|
| 文件声明了 `timescale | 6/89 | 7% | `weak` |
| 模块使用 ANSI 风格端口列表 | 86/90 | 96% | `strong` |
| always 块以时钟边沿为敏感条件 | 1505/3001 | 50% | `weak` |
| 时序块内出现过非阻塞赋值 <=（宽口径） | 868/1505 | 58% | `weak` |
| 时序块没有阻塞赋值（for 循环变量除外） | 1427/1505 | 95% | `strong` |
| 时序块敏感列表含复位边沿（异步复位） | 29/1505 | 2% | `weak` |
| 低有效复位命名为 xxx_n | 54/228 | 24% | `weak` |
| case 语句带 default 分支 | 114/146 | 78% | `moderate` |
| 使用参数/localparam 表示状态或常量 | 88/89 | 99% | `strong` |
| 端口声明显式写出位宽 | 1472/2620 | 56% | `weak` |

## 复现

```powershell
python scripts/ingest_open_source_conventions.py            # 联网，按固定提交拉取并度量
python scripts/ingest_open_source_conventions.py --offline  # 复用本地缓存，完全离线
```

## 许可证与权利边界

- 本文件与其 JSON 产物由本项目（Apache-2.0）授权；
- 上游项目的权利归属不因本次度量而改变；本项目未复制、未修改、未再分发其代码；
- 上表中的许可证与固定提交号可据以复核度量结果；
- 每文件的 sha256 指纹记录在 JSON 产物里，可验证度量确实针对该提交。

## 给 AI 规划器的接入方式

```python
from iverilog_ai.core.conventions import load_conventions, render_conventions_context
context = render_conventions_context(load_conventions(Path('data/opensource_conventions.json')))
```

生成的片段会随 `plan_tests(...)` 的上下文一起发送。它**不改变判定口径**：
testbench 仍由确定性模板生成，PASS/FAIL 仍只由 Icarus 与结构化断言决定。

## 给 AI 规划器的实际片段（预览）

```text
以下约定来自对开源 Verilog 项目的实测统计（非本项目自定规则）。
它们用于让你的测试计划更贴合社区惯例；它们**不改变判定口径**，也不能作为期望值的依据。
- 来源：alexforencich/verilog-axi @ 516bd5dadc33（MIT），共度量 83 个 Verilog 文件
- 来源：ZipCPU/wb2axip @ 2e8d3bc2d26d（GPL-3.0-or-later），共度量 89 个 Verilog 文件
测得约定：
- 文件声明了 `timescale：83/83（100%）
- 模块使用 ANSI 风格端口列表：55/55（100%）
- always 块以时钟边沿为敏感条件：125/125（100%）
- 时序块内出现过非阻塞赋值 <=（宽口径）：125/125（100%）
- 时序块没有阻塞赋值（for 循环变量除外）：120/125（96%）
- 使用参数/localparam 表示状态或常量：83/83（100%）
- 端口声明显式写出位宽：1448/2243（65%）
- 模块使用 ANSI 风格端口列表：86/90（96%）
```
