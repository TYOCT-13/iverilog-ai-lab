# 私有 RTL 样式候选与验证收据

最终候选为 `attempt-r3/targets/` 下的六个 RTL。官方严格生成式交付门禁结果为 `delivery_ready=true`、零错误、零严格警告。原 3 项 VG013 和 9 项 VG146 已在这个独立候选中解决；冻结 benchmark RTL、旧实验记录和 API 成绩均未修改。

| 官方公开门禁 | 实际状态 |
| --- | --- |
| compile | passed |
| ast | passed |
| readability | passed |
| comment | passed |
| naming | passed |
| profile | passed |
| testbench | not_requested |
| toolchain | not_requested |

以上状态来自 `gate-r3/deliverable_gate.json`，没有手工修改。CLI 的 `--include-testbench` 只控制静态扫描，没有现有仿真证据导入参数；此入口把外部工具链结果留给 validation readiness。真实 Icarus 证据另存于 `validation/public-oracle/` 和 `validation/four-state/`。

内部四位计数寄存器正规命名为 `cnt_event_o`，完整输出位桥接为 `assign o_count = cnt_event_o[3:0]`。这是同宽静态位连接，没有增加状态或延迟。普通嵌套 case 保留原清除/许可优先级；仅精确匹配 1，其余控制值进入原后续条件路径。异步复位 if 和所有 always 的目标、时钟、复位边沿保持。

事件许可/事件输入及 C 的优先级输入按明确两位宽度拼接为控制选择码。拼接源仍在官方 formatter AST 与完整传递组合锥中；没有靠别名遮蔽操作。原与候选的官方组合锥复用结果见 `operation_cones.json`。

| 目标 | 原操作数 | 候选操作数 | 强预算 |
| --- | --- | --- | --- |
| event_accumulator A 的计数 D 输入 | 7 | 3 | 3 |
| event_accumulator B 的计数 D 输入 | 5 | 3 | 3 |
| event_accumulator C 的计数 D 输入 | 9 | 3 | 3 |
| valid_data_pipeline A/B/C 的输出字 D 输入，各自 | 4 | 2 | 3 |
| valid_data_pipeline A/B/C 的捕获字 D 输入，各自 | 4 | 2 | 3 |

这些是门禁对结构化操作节点的计数，不是综合后的门级深度、PPA 或物理时序结果。canonical formatter 两遍字节稳定，配置没有覆盖或规则抑制。结构和哈希收据在 `final_receipt-r2-complete.json`，逐变体改动在 `diffs/`。

新增 DUT 执行共 **36 次**：公开逐拍判据 12 次，四态差分 24 次；原件和候选各 18 次。所有编译与执行退出码均为 0，API 请求为 0。本收据独立于旧 108/2033/其他 API 实验成绩。

公开判据由项目原有 `VerificationPipeline`、固定 `DutContract` 和逐拍语义模型运行。六对的全部真实输出观测逐行相同。A 均通过正确功能判据；event B/C 各有 1 项原错误检查失败，pipeline B 有 5 项、C 有 1 项，原件与候选的失败数和判据一致。B 仍忽略事件许可；C 的清除仍受许可限制；流水 B 的有效标记仍提前，流水 C 的有效标记仍忽略 flush。

四态差分使用项目现有观察驱动，驱动本身有零断言；报告的通过来自外部真实逐行等值比较。事件部分覆盖全部 64 种 clear/enable/event 四态控制组合，交替从 1 和 15 开始，另有 8 种未知复位场景。流水部分覆盖全部 64 种 reset/flush/valid 四态组合、四种捕获资格历史和已知/混合 X/Z 数据。非时钟采样验证异步复位行为；clear 为 X/Z 且 enable/event=1 的后续计数路径也得到实测覆盖。公开判据及四态部分共比较 **5115 个输出值**，全部相同。

`diagram-encoding-r1/bundle/spec/targets/` 已由登记入口 `workflow.write-spec` 生成六份同名 `<module>_spec.md`、六份 WaveJSON 和六份 SVG，且逐变体交叉核对模块/端口。B/C 文档明确描述其原故意错误行为，图中的 after 输出也采用各自实际规则；它们没有借 A 规格宣称功能正确。SVG 采用简短头标题，图为声明规格时序，不是实测轨迹。主代理已逐张真实浏览修正后的六 SVG，完成作者 AI 视觉验收（非 H02）。

失败证据完整保留：第一轮 `gate-r1/` 为 23 错误；第二轮 `gate-r2/` 为 4 错误、3 严格警告；对应原始和格式化候选仍在各轮目录。首次 write-spec 从 skill cwd 调用因 workspace 路径范围拒绝而退出 2，其 stdout/stderr/退出码位于 `attempt-r3/spec-render-logs/`；随后使用项目 cwd 与仅子进程 PYTHONPATH 的登记入口成功，成功证据在 `spec-render-logs-r2/`。

语义相同的仿真证据不是形式等价证明。四态组合不是所有数据和内部状态的笛卡尔积穷举；计数所有 16 个值在公开二态填充/回绕序列中经过，但四态控制只使用 1/15 种子。未运行综合、实现、物理时序、硬件或远程验证。项目自动生成的测试台是验证证据工件，没有声称它们通过严格 readable testbench 门禁。依赖预检记录 remote 技能缺失、WaveDrom 3.6.1 可用；没有安装依赖。

主代理浏览原 SVG 后指出连续重复的二值字符会出现细小尖峰或缺口。本轮仅把 pipeline A/B/C 的 i_valid 和 o_valid 共六条信号中的重复二值改为 WaveDrom 的 `.` 保持符，注册 write-spec 三次退出码均为 0。24 条二值信号在实际输出 WaveJSON 中逐拍解码一致，clock、bus、data、title、其余字段不变。原 21 份输入/伴随文件按旧 members.json 的 SHA-256 核对全部保留，六个原件和六个候选 RTL 哈希未变；没有新增 DUT 执行，累计仍为 36，API 请求仍为 0。

编码与实际生成物核对证据分别在 `diagram-encoding-r1/encoding_equivalence.json` 和 `diagram-encoding-r1/rendered_bundle_validation.json`，成功渲染日志在 `diagram-encoding-r1/render-logs/`。新的六份 spec/SVG 位于 `diagram-encoding-r1/bundle/spec/targets/`。主代理随后实际逐张浏览了修正后的六 SVG，尖峰/缺口消除，标题、端口和数值完整；该状态来自真实浏览器验收回执，而非仅渲染成功。旧 final_receipt.json/.md、members.json、原 SVG 与 WaveJSON 均未覆盖。


最终视觉回执是主代理所有的 `style-visual-r2/root_visual_receipt.json`，作者为 root authoring AI，非人类 H02；六份 PNG、geometry JSON 与最终 SVG 的哈希逐项绑定。初次六图留在 `style-visual-r1/`，不能声称从未失败。原始 text 矩形包含缩进空白，潜在越界诊断保留；可见字形没有裁切，未声称零几何警告。

可供上层流程选用的私有源路径：`E:/FPGA_WORK/iverilog-ai-lab/.iverilog-ai/ic-engineering-preflight-20261007/candidate-r3/attempt-r3/targets/<event_accumulator|valid_data_pipeline>/<A|B|C>/<module>.v`。

最终伴随规格路径：`E:/FPGA_WORK/iverilog-ai-lab/.iverilog-ai/ic-engineering-preflight-20261007/candidate-r3/diagram-encoding-r1/bundle/spec/targets/<module>/<A|B|C>/<module>_spec.md`，对应 `waveforms/<module>_variant-behavior.json5/.svg`。具体六模块路径和 SHA-256 在总收据 `module_bindings_and_invariants` 中。它们尚未合并到正式材料或冻结 benchmark。

复现入口为 `E:/FPGA_WORK/iverilog-ai-lab/.iverilog-ai/ic-engineering-preflight-20261007/candidate-r3/reproduce.py`。在项目 cwd，用 `D:/Users/TYOCT/anaconda3/python.exe -B -X utf8 <entrypoint> <fresh_run_name> --mode all` 可重新运行官方门禁、注册 write-spec 与两组原件/候选语义验证；`gate`、`spec`、`semantics` 可分别运行。输出限定到新 `candidate-r3/replays/<fresh_run_name>/`，已存在的名称会拒绝，不覆盖本次证据。语义复现保留原 vectors/contracts/比较逻辑，仅改三处输出目录表达式。入口只做过无 DUT 的语法编译和 `--help`（退出 0），没有为了检查 wrapper 再跑 36 次；若将来调用 all/semantics，产生的额外 36 次必须作为新 replay 单列，不能加进本次既有 36 次或旧 API 成绩。
