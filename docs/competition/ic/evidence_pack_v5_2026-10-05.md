# ICARUS v5 本地证据包

日期：2026-10-05；生产源码 `4d8eafb97681eb96ffe5477b1840bb46558256fa`。新包保存逐拍检查与独立补测版本的原件；旧v4/c7完整包另行保留，不替换。

## 包与核验

- 本地ZIP：[ic-agent-v5-evidence-20261005.zip](../../../.iverilog-ai/ic-agent-v5-evidence-20261005.zip)，48,306,453字节。
- SHA-256：`d710a75c651acb4ed64622325b281dbf091660625f70eea3f87703ad8655f3f8`。
- 3,282条目，其中3,281文件的大小与SHA逐项匹配；manifest自身不计入其哈希列表，避免循环。ZIP CRC和完整集合核验通过。
- [构建原始回执](evidence_pack_v5_2026-10-05.json)保存范围、源码版本和包摘要；字节核查与真人独立性无等价关系。

[独立子代理包后核查](../../review/ic_v5_pack_review_2026-10-05.md)及[回执](../../review/ic-v5-pack-review-2026-10-05/receipt.json)复算上述全部集合、74快照、60任务/150执行侧、41请求与预算，并比对既有离线重放日志；未发现实质冲突。耗时的3.55e-15浮点尾差保留原始值并解释，不改变成绩。没有新增API、仿真、真人或H02，也没有重新核验每次远程响应。

`source/`为4d8eafb的Git源码归档；Git可能按属性转换换行，实际评测登记的74份字节快照以`raw/agent-comparison-v5-live-20261005/registered-inputs/`为准。它们在请求前冻结、按原字节保存，不能拿归档后换行替代原注册SHA。

## 包含范围

1. 本轮60登记任务、41真实API请求的完整results/summary、每轮真实计划、stdout、参考审核、采样与轨迹；包含正确FIFO的一次格式拒绝及无反馈握手漏检。反馈8/8与随机等基线8/8持平，未抹去失败。
2. 逐拍期望/执行指纹的代理代码检查、旧UART/SPI计划零API采样诊断、独立/追加调度实际Icarus重放与预检回执。
3. 完整回归及浏览器最终、首轮失败原件；公开摘录、日志和三尺寸截图。手机是视口模拟。
4. 从真实v5 API首轮导出的UART反例小包，包含RTL、测试台、采样、波形及独立`replay.py`。

完整允许目录清单在包内`manifest.json`与公开JSON回执中。没有收集私下API配置、整个工作区或旧实验目录。主动凭据的明文/JSON形式及解码JSON扫描共4,008项，命中0；不声称通用秘密扫描认证。未跟随符号链接或Windows重解析点。

本轮包不包含旧v4/c7的全部原件、后续包审计及重放回执、其他历史试验或构建依赖。旧包继续由[evidence_pack_v4](evidence_pack_v4_2026-10-04.md)管理。后续回执独立保存并引用本包SHA，避免自包含循环；旧绝对路径原样留证，全量汇总在解包后重定位执行尚未核验。

## 仓库之外的真实离线重放

实际从外层ZIP提取`raw/ic-agent-v5-offline-demo-20261005/`全部13文件至新Temp目录，运行包内脚本，不导入项目模块、不调用API。编译和执行退出0；**108输出比较、16失败记录、`failed_checks`**，与原run `d52a1836ec44`的结构化stdout完全相同；11个清单文件执行前后字节均无变化。

[实际回执](../../experiment/ic-agent-v5-pack-replay-2026-10-05/receipt.json)、[过程stdout](../../experiment/ic-agent-v5-pack-replay-2026-10-05/stdout.log)、[仿真stdout](../../experiment/ic-agent-v5-pack-replay-2026-10-05/run.stdout.txt)。这是同机既有Python/Icarus环境中的解包重放，不是异机、干净安装、真人试用或H02。退出0只表示重放完成，不表示存在位序错误的DUT通过。

重放首次辅助脚本误按12文件计数，遗漏README.md，在启动Icarus前停止；[首次记录](../../experiment/ic-agent-v5-pack-replay-2026-10-05/first-attempts/replay-r1.json)保留。修正为对清单与完整文件集合核验后，在另一个新目录完成；原包未修改。打包首次预检的[目录名错误](../../experiment/ic-agent-v5-pack-replay-2026-10-05/first-attempts/pack-helper-preflight.json)亦保留，不计API或DUT失败。

解包后可自行重放：

```powershell
python replay.py --iverilog D:\iverilog\bin\iverilog.exe --vvp D:\iverilog\bin\vvp.exe
```

需要安装Python和Icarus，可按自己的路径调整工具参数。脚本验证原RTL与测试台SHA，只执行已保存测试台，不能扩展成电路完全正确的证明。

## 仍待完成

真人试用、独立人工H02、新模块留出、多次同版本重复、实体手机、异机完整复现、API账单、演示视频、真实远程仓库和正式提交仍待完成。正式v2 PDF/答辩仍表示28be1ed，当前[v5实验](../../experiment/agent_comparison_v5_live_2026-10-05.md)与[工程验收](../../experiment/ic_agent_v5_validation_2026-10-05.md)单独保存。
