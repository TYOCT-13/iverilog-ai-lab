# 本轮c7/v4证据包代理字节核对

本记录由未参与本轮打包脚本实现的代理读取完成版ZIP与本机原件形成。它是本地机器复核，不计H02真人独立审核、异机复现或正式提交。审核未读取真实凭据，API请求0、仿真0，未修改包内文件。

对象为`.iverilog-ai/ic-agent-v4-evidence-20261004.zip`，127,448,982字节，SHA-256 `768c3c91b1fca0cf86683580a463de8dc4b30228d4b67335781e6773bc25570c`。

| 检查 | 结果 |
|---|---|
| ZIP CRC、成员与安全路径 | 10,331成员正常；无重复、额外、缺失或危险路径 |
| manifest字节 | 10,330项SHA与尺寸全部匹配；manifest自身不循环哈希 |
| c7原件 | 252行results及summary与原目录字节一致 |
| v4原件 | 84行results及summary与原目录字节一致 |
| 四源码归档 | 名称、commit注释、文件集合正确；重新git archive产物逐字节一致 |
| 脚本换行 | 每归档6个Windows脚本由LF转CRLF，提交内.gitattributes明确eol=crlf，属于预期导出 |
| 注册输入 | 281登记中280匹配：269工作区原字节、9 Git原字节、2明确记录的CRLF恢复；跨组重复计条目 |
| 唯一缺项 | UART应用登记的旧计划MD，SHA e072ac312e1fd1c82097b62a90f2a427ae17cd3dc62ae337365ebf12c1482b6c；与交接说明一致 |
| junction反例 | 链接本体及其子路径未入ZIP；SafePathError拒绝JSON保留且SHA匹配 |

完整机器回执的[字节副本](ic-v4-pack-review-2026-10-04/receipt.json) SHA-256为`d9f3ba87b07e2ba5d4de92a0231f33b98fc8353f89281106ef782c68f8b75b53`。最初未分类的回执仍在私有审核目录；后续回执将Git属性允许的CRLF转换明确归类，未改源码或原始实验。

复核未发现新增差异，但已披露的旧文档缺失仍存在。哈希匹配只说明文件身份，不证明判据全面、模型优越或来源独立。包后反例仿真由根代理另行执行，见[338比较/48失败重放](../experiment/ic-agent-v4-pack-replay-2026-10-04/receipt.json)，不与本次仅字节审核混为同一操作。
