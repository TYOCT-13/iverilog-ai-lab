# 新评测入口：干净Git源码验收

本地提交`e7223dc`的完整源码字节与实际测试副本逐项匹配（692文件）。副本由Git导出，不带`.git`或私有`.iverilog-ai`运行记录；实际导入的diagnostic与Agent均来自副本的源码目录，不回退到原仓库模块。

发现新单元测试依赖本机父实验后，改用显式模拟的父结果及SHA关联账本。真实诊断原件、方案、入口和成绩不变，旧测试记录继续保存。最终**25项定向测试通过，0失败/0错误/0跳过，10.89秒，0API、0密钥读取**。

[机器回执](receipt.json)、[完整测试日志](pytest.log)、[JUnit](pytest.xml)、[源树记录](source_receipt.json)、[实际模块来源](import_receipt.json)。源树`97d8ca97f490fbe8200fd6a0ff605b08f7f733f1`由上面的真实本地提交保存；既有私有父结果在测试副本不存在。

同机、已有Python/Icarus依赖；这是源码副本测试，不是外部Actions、异机安装、全仓新回归或真人试用。20/24/5等旧定向运行不相加成总测试数；生产全仓1170/2属于此前冻结版本。

复现需在无私有运行数据的源码检出中先安装项目依赖，再运行：

```powershell
python -X utf8 -m pytest -q tests/core/test_agent_smoke_diagnostic.py tests/core/test_agent_smoke_comparison.py tests/core/test_agent_comparison_v3.py tests/core/test_agent_comparison_summary.py
```
