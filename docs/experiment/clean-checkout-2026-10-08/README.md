# 干净克隆验证原件

源提交 `1c29a8f0bffccf1dc373ac4f3c670ff212141f0a`，同一Windows主机的新Git副本与独立venv。最终2020通过、16跳过，0失败/错误；不计真人、异机、H02或新API成绩。完整说明见 [报告](../clean_checkout_2026-10-08.md)，操作见 [当前指南](../../reproduce_current.md)。

| 文件 | 内容 |
|---|---|
| [receipt.json](receipt.json) | 完整口径、实际命令、环境、跳过项、完整性与限制 |
| [pytest.xml](pytest.xml) | 最终完整JUnit，含全部16项跳过 |
| [mypy.stdout.txt](mypy.stdout.txt) | 88文件零错误 |
| [dead-code.stdout.txt](dead-code.stdout.txt) | 236项目文件零发现，排除第三方venv和临时产物 |
| [doc-index.stdout.txt](doc-index.stdout.txt) | 源提交的286/286材料路径；不检查全部Markdown链接 |
| [raw_evidence.zip](raw_evidence.zip) | 1242成员、2500794字节；全部SHA/CRC实际核验 |
| [raw_manifest.json](raw_manifest.json) | ZIP内每个成员的大小及SHA256 |
| [closure_receipt.json](closure_receipt.json) | 新文档链接、发布后索引291/291及原件复核 |
| [delivery_manifest.json](delivery_manifest.json) | 本目录文件SHA及发布时移动文档快照，清单自身排除 |

ZIP包括首次失败和最终日志、命令、JUnit、36次搬迁RTL重放全部原件、98例手写台矩阵及CLI控制原件。排除Git数据库、venv、包缓存、API配置/凭据和完整pytest临时目录；全套测试的逐案例临时DUT目录仍在作者本机，不声称ZIP含有它们。

ZIP SHA256：`66d497808e17297302b48838c8c4d6fe65766beade54ea82a408f2ef6979c654`。

已封存的138份RTL维护包内部文件、49份旧规格包文件、v3材料及旧API原件保持原样。它们的外部README/INDEX/指标等绑定是当时发布提交4a7804e的快照，后续移动文档应从对应提交读取；本轮没有改写旧清单来让它匹配新文档。

16项跳过分别为14项未随Git分发的旧外部输入、1项Windows符号链接权限、1项空推荐断言表。另一台设备、真人/H02、外部Actions、真实视频和提交回执仍待真实操作。0模型API，安装包网络不计作模型请求。
