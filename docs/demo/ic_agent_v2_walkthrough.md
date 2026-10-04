# 数字 IP 验证：操作、反例与离线复核

日期：2026-10-04。本文对应本轮协议、端口采样和功能场景改造；真实 API 对照试验另行登记。这里的 UART 操作记录来自机器运行，不是真人试用。

## 1. 从网页启动验证

在仓库根目录运行：

```powershell
python -m streamlit run ui/app.py --server.port 8600
```

打开工作台，选择「UART 发送器」。先读 `spec/uart_tx_spec.md`：本案例默认每位4拍，接收启动的 E0 到 busy 释放的 E40 共需41个实际观察周期。时钟、复位和接口在案例合约中配置。

在「工具设置」选择在线模型，使用自己的 API 配置。现有本地私有配置可以继续使用；密钥文件不放进 Git 或证据包。回到工作台，填写具体目标，例如「发送 0x55 与 0xA6，检查 8N1 帧、忙期间重复启动、帧结束与复位恢复」。

展开「自动验证 Agent」，设置请求、轮数、累计激励周期，并勾选「根据场景覆盖缺口补测」。本轮对照实验的周期上限为：

| 案例 | 累计激励上限 | 主要观察 |
|---|---:|---|
| 单时钟 FIFO | 160 | 空满边界、溢出/下溢尝试、同拍读写 |
| UART 发送器 | 512 | 完整帧、busy 窗口、忙期间启动、复位 |
| SPI 主机 | 384 | 完整传输、done 脉冲、忙期间启动、复位 |
| Valid-Ready 握手级 | 160 | 接受、反压保持、传输与同拍替换 |

这些是开发集的实验参数，不是所有 RTL 的通用建议。已有计划会先执行；追加或替换后的整份计划重新仿真，重复执行也计入累计激励。复位和单独的正确基线审核另列，不能把累计周期写成总物理运行时间。

启动后检查停止原因、实际请求数、每轮检查和失败，再读「功能场景」。已观察、尚未观察、证据不足分别保留；覆盖命中不说明功能正确。当前只为四类经过审计的默认参数合约提供内置功能场景，自定义 RTL 需要自己的规格与判据。

## 2. 交接结果

下载 Agent 轨迹和场景记录。结果区导出的证据包包含可重放的原 RTL、生成测试台、结构化结果、文件 SHA 和 `replay.py`。涉及未打包的外部 include 时不标为可独立重放；原 RTL 或测试台已经变化时拒绝打包。

接收者安装 Python 与 Icarus，把证据包解压到新目录：

```powershell
python replay.py --iverilog D:/iverilog/bin/iverilog.exe --vvp D:/iverilog/bin/vvp.exe
```

重放不请求模型。每次保存到新目录；退出码0表示重放完整结束，设计结论另看 `passed` 或 `failed_checks`。确认是原来的反例，而不是只确认命令退出成功。

## 3. 已完成的 UART 应用演练

以下使用协议随机策略及真实 Icarus，零 API 请求。它展示一次完整验证与交接流程，不是 Agent 能力成绩，也不代表实际芯片工程使用。

```powershell
python scripts/run_agent_comparison.py --profile v2 --execute --cases uart_tx --strategies protocol_random --repeats 1 --total-request-cap 0 --output-dir .iverilog-ai/application-uart-v2-20261004
python scripts/summarize_agent_comparison.py .iverilog-ai/application-uart-v2-20261004/results.json --output .iverilog-ai/application-uart-v2-20261004/summary.json
```

原输出目录已存在；复测请换新目录，不能覆盖本次原件。

| 输入 | 激励周期 | 端点比较 | 不一致 | 功能场景（已观察/缺口/未知） |
|---|---:|---:|---:|---|
| 正确 UART | 512 | 338 | 0 | 6 / 0 / 0 |
| MSB 优先发送变体 | 512 | 338 | 48 | 5 / 0 / 1 |
| busy 不释放变体 | 512 | 338 | 136 | 3 / 1 / 2 |

每个计划还在正确基线上独立审核，三项都通过；严格汇总 `eligible_for_frozen_comparison=true`。两个缺陷均检出，正确输入未误报，分母为预先登记的2个开发集变体。48和136是不一致检查次数，不是发现的独立缺陷数。

将 MSB 变体的实际结果打包后执行包内 `replay.py`，再次得到338比较、48不一致、`failed_checks`，API请求0。新重放记录位于 `.iverilog-ai/application-uart-v2-20261004/portable-failure/replay-5f322e4e068b/`；证据包位于同级 `portable-failure.zip`。逐周期采样来源为测试台采样语句，与原执行 stdout 及文件 SHA 双重核对。

真实网页离线演练另外得到29向量、58/58比对一致，切页后结果保留；1440×900、1920×1080、390×844均未出现横向溢出。手机是桌面浏览器尺寸模拟，未检验实体手机。原记录为 `.iverilog-ai/agent-v2-browser-20261004-v3/results.json`；前两次浏览器脚本定位器失败也保留在旧目录，没有把它们删除后宣称一次通过。

## 4. 录制与真人复核

录制3–5分钟时，依次展示：规格与接口、请求/周期限制、真实执行、一个反例、未知或不支持的边界、证据导出与零请求重放。可以采用已保存原件快速重放，并说明使用固定原件；不要剪成模型每次都会成功或每个场景都已覆盖。

实际使用者按 [参与者入口](../trial/participant_start.md)独立操作，观察者记录用时、求助和卡点；不要提前给出结果答案。另请非对应实现者依据 [独立审核指南](../review/independent_review_guide.md)核查规格、判据、原始文件和统计。机器演练和代理交叉检查分别登记，不能填写为真人或 H02。
