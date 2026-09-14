# 变更记录

本文件记录对**可核验结论**有影响的变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

说明：本项目在参赛周期内以提交历史推进，版本号在首次公开发布时确定。
下方按阶段归类，每一条都可在仓库对应提交中找到证据。

## [未发布]

### 新增

- **当前基准上的双模型 10 次重复对比（真实 token 消耗）**：13 案例 / 67 缺陷 × 每案例
  10 次重复 × 2 个模型（各 130 次真实请求）。`deepseek-flash` 检出 **65/67（97.0%）**、
  `deepseek-v4-pro` **64/67（95.5%）**，两者参考误报**均为 0**；更强的模型计划合法率更高
  （100% vs 96.2%）但生成慢 **3.4 倍**（118.6s vs 35.3s），token 几乎相同（+0.8%），
  检出反而少 1 个。**两模型的漏检集合几乎不重叠**（交集仅 1 个缺陷，并集 66/67）。
  记录见 `docs/experiment/model_comparison_2026-09-12.md`（机械汇总表见
  `docs/experiment/model_comparison_r10.md`）。
- **当前基准上的 10 次重复在线实验（单模型完整记录）**：`deepseek-flash` 在
  13 案例 / 67 缺陷 × 每案例 10 次重复（130 次真实请求）下检出 **65/67 = 97.0%**，
  参考误报 **0**；同批基线为固定向量 56/67（83.6%）、随机 51/67（76.1%）、
  离线 MockProvider 51/67（76.1%）。2 个漏检的相位/观测原因、5 次被严格校验拒绝的
  请求（同一根因）全部逐条公开；token 1,229,171（按请求去重）。记录见
  `docs/experiment/online_model_r10_2026-09-12.md`。
- **多模型公平对比实验**：同一批案例（12 案 / 62 缺陷）跑两个真实模型，检出率完全相同
  （58/62 = 93.5%）。`deepseek-v4-pro` 的 AI 期望值准确率比 `deepseek-flash` 低 11 个
  百分点，检出率却一致——这是权威预言机设计的直接证据。记录见
  `docs/experiment/model_comparison_2026-09-11.md`。
- **token 费用估算**：`data/model_pricing.json` 价格表带来源与核验日期；
  `core/pricing.py` 只在价格已核验时给出金额，未核验时明确报"未估算"（`null` 不等于 0）。
- **本地试用材料**：`docs/trial/` 的任务卡、反馈表、结果页与汇总脚本。
- **上游贡献材料包**：`docs/competition/upstream_contribution.md`，含两份可直接提交的
  Issue 草稿与提交前检查清单。**尚未提交**——实际提交需要维护者的账号。
- **CI 工作流**：Linux 与 Windows × Python 3.11/3.12 四组合，跑全量测试、基准矩阵与
  编码卫生检查。工具位置改由 `core.toolchain` 统一探测（环境变量 → PATH → 常见目录），
  因此 CI 里是**真正执行**仿真，而不是把测试 skip 掉。
- **协作门面文件**：`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、
  `CHANGELOG.md`、`CITATION.cff`、Issue 与 PR 模板。
- **BOM 与编码卫生检查**：`scripts/strip_bom.py`，可在 CI 中作为门禁（同时检测 UTF-8 BOM
  与被写坏成成串问号的中文注释）。
- **开源规约知识摄取**：`core/conventions.py` + `scripts/ingest_open_source_conventions.py`，
  从真实开源项目实测编码约定（含出处、许可证、每文件 sha256），注入 AI 规划上下文。
- **信号活动覆盖率**：`core/coverage.py`，从 VCD 事件推导两个指标——活动比例（哪些信号
  动过）与**取值覆盖**（到达过多少种取值）。只加活动比例时指标没有区分力：`mod10_counter`
  在"使能恒 0、从不计数"的弱激励下活动比例仍是 100%（复位清零也算变化），加入取值覆盖后
  同一对比为 38% vs 6%。口径与"这**不是**代码覆盖率"的边界见 `docs/coverage.md`。
- **期望值证据等级改为三态**：`reference_model`（参考模型复算并覆盖）/ `ai_generated`
  （用的是 AI 数字）/ `none_given`（本轮没有期望值）。第三态来自缺陷修复，见下。
- **多模型对比脚本的可比性检查**：案例集合不一致时直接拒绝出表，不把不可比数据并排。
- **综合矩阵脚本（可复现）**：`scripts/run_synthesis_matrix.py`，98 个变体逐个跑 Yosys；
  此前 `docs/layered_evidence.md` 的"全部可综合"是一次性命令跑出来的，读者无法复现。
  判据是"有没有拿到统计"而非退出码，`unavailable`/`timeout`/`error` 单独计数且**不计入通过**。
- **案例表收拢到一处**：`core/benchmark_cases.py` 提供 `CASE_TABLE` 与
  `validate_case_table`。原先"案例 → RTL/testbench/顶层"的映射在基准矩阵脚本、策略实验
  脚本与网页各写了一份且互不校验，存在**静默漏跑**风险（manifest 加了案例、脚本没加，
  分母变小而"全过"的结论毫无变化）。现在基准矩阵在开跑前先校验，缺一行直接报错。
- **未可达代码检查**：`scripts/check_dead_code.py`（AST，保守判据：终止语句之后的代码、
  无限循环之后的代码、**同一作用域内重复定义**）+ CI 门禁 + `pytest` 内的同款断言。
- **类型门禁（mypy）**：`pyproject.toml` 的 `[tool.mypy]` + CI 步骤 +
  `tests/core/test_type_check.py`；`src` / `ui` / `scripts` 当前 0 error。
- **离线 AI 路径矩阵（无需密钥）**：`scripts/run_pipeline_matrix.py` + CI 步骤 +
  `tests/core/test_pipeline_matrix.py`。判据是"跑通 + 无失败记录 + 期望值来自参考模型 +
  生成了 testbench + 报告里有覆盖率证据"。
- **CLI 契约测试**：`tests/core/test_cli.py` 把退出码约定（`run` 0/1、`plan-run` 0/1/2、
  `compare-rtl` 0/1/2、`report` 0/2、`validate-plan` 0/2）与产物路径钉成断言。
- **`verdict` 单一结论词**：`SimulationResult.verdict`（`passed` / `failed_checks` /
  `failed` / `inconclusive`），写入 `result.json`、CLI 摘要与报告首部。
- **基准规模 78 → 80 缺陷（`sync_reset` 扩到 4 个变体）**：`sync_reset` 原先只有 2 个缺陷，
  而复位同步是 CDC 高危点，因此按"根因独立"补足，覆盖复位**释放**与复位**断言**两条不同的
  错误路径。其后复核发现其中一个变体与既有变体代码相同，已替换（见下方修复）。
- **基准规模 15 案例 / 83 缺陷（+ `pulse_stretcher`）**：`pulse_stretcher` 此前只是网页里的
  演示案例（有 RTL、testbench、spec、contract，却不在基准清单里），现在补齐为正式案例：
  参考模型逐拍对齐（15/15）、3 个根因独立的缺陷变体、24 条检查的边界 testbench。
  交接的教训见下方「手写 testbench 也会被门禁跑一遍」。
- **参考模型的覆盖度门禁**：`tests/core/test_reference_model_coverage.py` 对每个已支持设计
  用"故意写错的期望值必须被判为不一致"证明诊断路径真的在比对；另断言两条路径给出同一组
  期望值、每个设计都产出可观测输出。
- **调试服务的设计名单不再手抄**：`ai.debug_server.KNOWN_DESIGNS` 改为取自
  `debug_provider.known_designs()`，由 `tests/core/test_debug_provider_coverage.py` 把
  "激励表 / 参考模型 / contract 端口名"三者钉在一起（信号名拼错会直接失败）。

### 修复

- **检出率用了不可比的口径（把"多试几次"算成"模型更强"）**：在线模型跑了 10 轮，
  而我报的 `97.0% / 95.5%` 是"任意一轮检出即算检出"的**累计并集**；固定/随机/离线三个
  基线各只跑 1 轮。拿 10 轮并集比 1 轮结果，等于把重复次数算成了模型能力。经复算，
  **同口径的单轮平均**是 flash **85.8%**（范围 70.1%–91.0%）、pro **87.8%**（82.1%–91.0%）——
  相对人工固定向量（83.6%）只高 **2.2 / 4.2** 个百分点，而不是并集数字看上去的 13–21 个百分点。
  已修正两篇实验文档与参赛材料，并让 `scripts/compare_models.py` 的对比表**同时输出两个口径**
  （累计并集 + 单轮平均），避免同类误读再次发生。
  顺带修正一个相关结论：按单轮平均，`deepseek-v4-pro` 反而**更稳**（平均更高、波动更小），
  flash 的优势只在"多轮并集更广"。
- **文档里的第一步 `pip install -e .` 在干净环境里会直接失败**：`pyproject.toml` 的
  `[build-system]` 写成 `requires = []`，而 pip 默认在**隔离环境**里构建——构建后端
  连 setuptools 都导不进来，报 `ModuleNotFoundError: No module named 'setuptools'`，
  哪怕本机已经装了 setuptools。评委或同学照 README 的第一步就会卡住。
  已改为标准的 `requires = ["setuptools>=61"]` + `setuptools.build_meta`；离线环境可在
  命令后加 `--no-build-isolation`，README / CONTRIBUTING / 试用任务卡都补了这一行。
  顺带核实：装好后 `python -m iverilog_ai` 与 `iverilog-ai` 控制台命令均可用
  （此前仓库内所有命令都靠 `PYTHONPATH=src` 才跑得起来，属于隐性使用门槛）。
- **token 总量按行重复累加，被放大 6 倍**：`usage` 挂在每个变体行上，而一次计划请求
  的计划会被同一案例的参考设计与全部缺陷复用——按行相加等于把同一份用量算了 13 次。
  实测：09-11 双模型对比的 `1,428,261` / `1,391,722` 实际是 **236,028 / 231,036**；
  09-10 单模型首测的 `639,307` 实际是 **113,204**。两篇实验文档已加"口径更正"说明
  （保留原数字并给出更正值），`scripts/compare_models.py` 与实验脚本改为按
  `request_id` 去重，并加了"4 行共享 1 请求 → 总量 1,000 而非 4,000"的回归用例。
- **长跑实验只在最后落盘**：真实模型实验可能跑几小时，一次中断就丢掉已经花掉 token 的
  全部结果。现在每进入一个案例就增量落盘（`partial=true`，原子替换），并在案例边界
  打印去重后的累计 token。`compare_models.py` 同时**拒绝**把 `partial=true`、
  未跑完或在线请求数不一致的记录放进对比表（否则分母悄悄变小而表格看起来完全正常）。
- **网页"生成计划"之后整页渲染中断（NameError）**：计划渲染分支里调用了一个不存在的
  函数名（`rules_manifest`，实际导入的是 `rule_manifest`），抛出的 `NameError` 又不被
  那里的 `except ValueError` 接住——于是"生成计划"之后，计划 JSON、执行按钮、结果区
  全都看不到。同一分支里 `_contract()` 也是"先用后定义"（`ui/app.py` 是线性脚本，
  模块级语句按顺序执行）。两者都已修正并前移定义，`tests/core/test_ui_smoke.py`
  新增"生成计划后页面仍然存活"的用例（已验证：修之前必失败）。
- **同名函数定义两次，前者是死代码**：`core/static_review.py` 的 `_numeric_findings`
  与 `scripts/markdown_to_pdf.py` 的 `_load_font` 各被定义两次，后一份静默覆盖前一份。
  行为没变（Python 本来就用后一份），但"改错那一份"的风险是真实的。已删除死副本，
  并把**重复定义**加进未可达代码检查。
- **开启类型门禁（mypy，0 error）**：`src` / `ui` / `scripts` 共 49 个文件，配置见
  `pyproject.toml`，CI 与 `tests/core/test_type_check.py` 双重执行。首轮修掉的既有问题
  包括：`repair_compare` 里 `getattr(after, "status", None).value` 的 AttributeError 隐患、
  `provider` 构造函数里 `getenv(...).strip()` 可能作用于 None、报告里一致性率的
  `None * 100` 类型歧义、`DutContract.parameters` 声明成"一定是 dict"却默认 `None`、
  `rtl_import`/`conventions`/`testbench`/`coverage` 的变量复用与标注不符等。
- **离线 AI 路径其实什么都没测（两个 bug 叠加）**：这条路径是"无密钥也能完整跑通"的
  门面，但实测发现它生成的计划**端口全空**：
  1. `DeterministicLocalProvider.generate()` 直接 `del prompt`，只用构造时传入的
     `design`/`contract`。于是最自然的用法 `plan_tests(objective, case, provider=DeterministicLocalProvider())`
     得到的计划里 `design` 是字面量 `"design"`——**参考模型整轮跳过**（`design not in SUPPORTED`），
     证据等级退化成 `none_given`；
  2. 调试服务从提示词里取合约的正则只认 `DUT context: {json} Schema:` 这一种形状，而真实
     提示词是 `rules_context(...)` 的产物：规则文本在前、合约以 `--- DUT contract ---` 附在末尾。
     于是合约解析为空 → `driveable` 为空 → **每条向量的 `inputs` 都是 `{}`**：计划合法、
     仿真"通过"，但 DUT 端口从头到尾保持初值。
  处理：Provider 改为"自身字段 → 提示词 → 仓库内置合约"依次解析；合约提取改为括号配对解析
  （非贪婪正则在嵌套对象上必然失败）；既无合约又非内置案例时**直接报错**，不再生成空计划。
  影响范围：网页"本地调试模型"与 `plan_tests` + 本地 Provider 的用法；策略实验自建计划，
  因此 `docs/experiment/` 里的离线数字不受影响。
  新增 21 条回归（`tests/ai/test_debug_interface.py` 的真实提示词形状用例 +
  `tests/core/test_expectation_evidence.py` 的端到端断言"设计名正确、每条向量都有激励、
  证据等级是 reference_model"）。
- **新增离线 AI 路径矩阵**：`scripts/run_pipeline_matrix.py`，15 个案例逐个走
  "确定性规划 → 生成 testbench → Icarus 裁决 → 权威期望值 → 覆盖率证据"，实测 **15/15**。
  基准矩阵用手写 testbench，覆盖不到这条路径——这正是上面那两个 bug 能长期藏着的原因。
  已进 CI，并有 `tests/core/test_pipeline_matrix.py` 兜底。
- **`verdict`：把 `passed` 的歧义收敛成一个结论词**。按裁决策略，功能不匹配记为 WARN，
  因此缺陷变体输出 `status="passed_with_warnings"`、`passed=true`、`failures=3`——
  一次"检出 3 个缺陷"的运行写着 `passed: true`，只看这个字段必然读错。现在 CLI 摘要、
  `result.json` 与报告都给出 `verdict`（`passed` / `failed_checks` / `failed` / `inconclusive`），
  报告里还写明"（N 条检查不匹配）"。`tests/core/test_verdict.py` 覆盖全部 7 种状态。
- **报告配图里的数字一直读不到真结果（图内自相矛盾）**：`scripts/make_report_figures.py`
  找的是 `benchmark_matrix.json`，而基准矩阵实际产出 `matrix.json`——于是它**永远**走回退
  分支，图 4 显示硬编码的 `14/14` 与 `78/78`，而同一张图里的柱状图是按清单现算的（总数 83）。
  处理：按真实产物名读取；读不到时只报"清单规模"，测量值留 `None` 并渲染成"—（未运行）"，
  **不用 0 或旧值冒充一次真实运行**。图 3 的综合层同样改为读综合矩阵产物：跑过写
  "实测 98/98"，没跑过写"未运行"，不再写死 `92 个变体全部通过`。
  新增 `tests/core/test_report_figures.py` 钉住这三条口径。
- **手写 testbench 也会被门禁跑一遍（`pulse_stretcher` 的复位检查一直是坏的）**：
  该 testbench 把 `rst_n` 初值声明为 0，之后又赋 0——**没有 negedge，异步复位从不触发**，
  `pulse_out` 停在 `X`。而 `X` 被直接打进了 JSON（`"actual":x`），记录因此是非法 JSON，
  流水线只能报 `malformed structured result`。它以前不在基准矩阵里，所以没人跑到；
  本轮把它纳入矩阵后立刻暴露。
  处理：复位改为"先拉高再拉低"造出真实 negedge；不确定值统一标注为 `"unknown"`
  （与边界 testbench 的既有约定一致）；并把展宽长度、重触发、回落都补成显式检查。
  教训：**一个从未被自动化跑过的 testbench，等于没有 testbench**。
- **"读取模型列表"与"检查配置"两个按钮从未在页面上出现过**：这两块代码被写在
  `ui/app.py::_build_provider` 的 `return` **之后**，是 150 行不可达代码的一部分，
  而所有静态测试都是绿的。`available_models` 只在死代码里被写入、从未被读取——
  也就是说这个功能从上线起就没工作过。
  处理：把两个按钮移回「AI 接口设置」面板，并让读到列表后可以直接**下拉选择**模型
  （覆盖手输的模型 ID），而不是把 ID 打在一行小字里让人手抄。
  新增 `tests/core/test_ui_smoke.py`：用 Streamlit 自带的 `AppTest` 真正渲染页面，
  断言这两个按钮存在——静态解析查不出"永远不执行的代码"。
- **参考模型里有一份 150 行的语义副本是死代码**：`check_plan_consistency` 在
  `return` 之后还留着一份完整的历史实现（自己重算 FIFO/UART/SPI/去抖/PWM…）。
  它不报错、不被覆盖，但会让读者以为诊断路径有独立实现，也会引诱后来者改错那一份。
  处理：删除死副本（活路径本来就委托给 `_DesignState.step`），并新增
  `scripts/check_dead_code.py`（AST 判据，保守：只报确定的不可达语句）+ CI 门禁。
  该检查顺带在 `static_review._consume_statement` 里发现一处多余的死 `return`，已删。
- **"看起来在检查、其实什么都没查"要有测试兜住**：新增
  `tests/core/test_reference_model_coverage.py`，用"把期望值故意写错必须被判为不一致"
  证明诊断路径真的覆盖到**每一个**已支持设计（含 `johnson_counter` / `edge_detector`），
  并断言两条路径给出同一组期望值、每个设计都产出可观测输出。
- **"83 个缺陷"里有一个是重复计数**：`srst_bug_single_stage_only` 与
  `srst_bug_single_stage` 的代码**逐字节相同**（只有 id 和注释不同），属于同一缺陷登记两次。
  它同时暴露了两个更早的问题：这类重复靠 id 唯一性检查发现不了，而且这两个文件的中文注释
  在写入时被编码破坏——整行中文退化成成串问号，语义永久丢失，而编译器不会报错。
  处理：删除重复变体，换成根因独立的 `srst_bug_sync_assert_only`（第二级触发器写成纯同步
  复位：释放仍两级同步，**断言**失去异步性），并用边界 testbench 实测确认它能被检出
  （`assert_pulls_low` 与 `reassert_immediate_low` 两条检查同时失败）。损坏的注释也已按
  缺陷语义重写（本文档不直接复制那行损坏样本，否则卫生检查会把它当成新的损坏）。
- **新增两道防回归门禁**：① 任意两个缺陷变体的代码本体（去注释去空白）不得相同、且缺陷
  不得与参考设计相同；② `scripts/strip_bom.py` 在 BOM 之外增加**编码损坏检测**
  （注释里出现成串问号、GBK mojibake 特征），因为被破坏的注释不会让编译失败。
  两道门禁都已进 CI。
- **重复登记时"补一个"的诱惑要显式拒绝**：本轮没有为了保住 80 这个数字而保留重复变体，
  而是换成一个真正不同的缺陷——数字不变，含金量变高。
- **期望值来源把"没有期望值"误标成"AI 生成"**：只有两态时，既无参考模型、AI 又未给
  `expected` 的自定义 RTL 会被标成 `ai_generated`，读者会以为有 AI 期望值在把关。
  补出 `none_given` 后三态各自对应真实情况，并补了防回归用例。
- **覆盖率统计把参数当信号**：`localparam RED=2'b00, YELLOW=...` 被算成"从未变化的信号"，
  在 `traffic_light_emergency` 上造出 7 个假缺口（活动比例 50%）。参数与存储器声明现已排除；
  同时修掉"只读到第一个名字就停"（`=` 截断）与 1 位标量宽度识别（ANSI 端口用 `,` 分隔）。
- **实测约定 JSON 被整篇拼进模型上下文**：`rules_context` 按 manifest 逐条读原文，把
  36KB 的约定 JSON 整篇塞进上下文，撞上 `plan_tests` 的 20000 字符上限，使**真实模型
  路径直接报错**。离线 MockProvider 不走这条路径，因此单元测试与基准矩阵都发现不了。
  修复后上下文从 38,310 降到 1,639–1,944 字符，并加了防回归断言。
- **探针两处错误**：复位命名用子串匹配把 `burst` 当成 `rst`（复位名从 35 个虚增到 491 个）；
  模块头正则不覆盖"参数与端口列表都换行"的真实写法（83 个文件只匹配到 4 个模块头，
  却算出 ANSI 端口 100%）。两者都已钉成回归用例。

### 记录（不修正史）

- **提交 `62619e6` 的缺陷扩展过程**：该提交把 `sync_reset` 从 2 个缺陷扩到 4 个，其中
  一个候选 `sync_reset_bug_chain_short` 在提交前被删除——它把 `sync_ff` 的输入从常量 1
  改成 `ext_rst_n`，但参考里 `rst_n <= sync_ff` 读的也是旧值，两者时序完全相同，
  **它与参考行为等价，不是缺陷**（单独跑退出码 0）。同时另两个候选（`mod10` 复位值错、
  使能无效时清零）因与已有 `bug_reset_one` / `bug_hold` 高度重合而不予注册。
  经复核，该提交新增的 `srst_bug_single_stage_only` 与既有 `srst_bug_single_stage`
  代码相同，已在本次修复中替换（见上）。
- 提交 `a08702e` 的信息里误写"另修正 case 探针等价的贪婪匹配"——实际未做该修改。
  `verilog-axi` 的 case 0/35 带 `default` 是真实测量结果（其 state 完全枚举），不是 bug。


## 阶段十二：行为级对比

### 新增

- `core/behavior_compare.py`：让用户 RTL 与参考 RTL 跑**同一份** TestPlan，逐检查项
  （`test_id` + `signal`）与逐波形信号比对；三态结论 `identical` /
  `different` / `records_identical_waveform_unavailable`。
- CLI 子命令 `compare-rtl`，退出码 `identical=0` / `different=1` / 无法判定=2。
- 网页在结构对比下方提供行为级对比入口与逐检查项差异表。

### 修复

- `compare_waveforms` 的 `status` 语义收紧：只描述**共有信号**。一侧多出内部辅助变量
  （如 `next_count`）是实现细节，不再被误判为行为差异；信号集合差异改由
  `same_signal_set` / `only_in_*` 单独表达。

## 阶段十一：分层证据

### 新增

- `core/synthesis.py`：可选 Yosys 综合证据层，产出「仿真 / 综合 / 时序 / 比特流 / 上板」
  五层证据表，未做的层级显式标 `not_run`。
- 报告与网页新增「分层证据」章节；综合层**不参与** PASS/FAIL 裁决。
- 实测 92 个 RTL 变体（14 参考 + 78 缺陷）全部可综合；负例（变量上界 `while`）必须报失败。
  （当时的一次性测量；后续变体扩到 94 个，并补了可复现脚本，见「未发布」。）

### 记录

- WASM 版 Yosys 的三个约束：`-s` 脚本不可读、`-q` 会静默 `stat` 输出、ABC 阶段静默中断
  （因此综合跑到 `begin:fine`，判据改为"有没有拿到统计"）。
- `#5 q <= d;` 这类延时会被 Yosys **静默忽略**——所以"综合通过"不能反过来当作
  时序语义正确的证据。

## 阶段十：参考模型全覆盖

### 新增

- johnson_counter、edge_detector 两个案例成套接入（RTL / contract / spec / 功能与边界
  testbench / 参考模型 / 逐拍对齐用例），各配 4 个独立根因缺陷。

### 变更

- 基准规模：**12 案例 / 70 缺陷 → 15 案例 / 78 缺陷**；固定矩阵
  **78/78 检出、0 误报、0 不可判定**。
- 参考模型对齐：**12/12 → 14/14**，`SUPPORTED == set(AUTHORITATIVE)`。
- `INPUT_DEFAULTS` 成为"向量未列出的输入取什么值"的单一事实来源，模型与实验激励
  生成器共用。此前 `debounce` 因两侧默认值不一致产生过 25 条伪失败。
- 页面前端新增"实证状态"面板（数字实时读取仓库现算）与"期望值来源"提示。

### 修复

- 修正 `rule_manifest` 重名导入冲突（`core.rules` 与 `core.static_review` 同名不同签名），
  该冲突会让页面实证面板静默退化成一排"—"。

## 阶段九：RTL 静态审查扩展

### 变更

- 静态规则：**9 条 → 44 条**（error 4 / warn 27 / info 13），每条配最小反例与最小正例，
  并有断言强制注册表与用例表一一对应。

### 修复（噪声校准）

- `division-operator` 曾把注释结尾 `*/` 当成除法（84/84 全命中）；
- `inferred-latch` 曾把合法写法误判为锁存器（15 条 error 级误报）；
- `missing-timescale` 因注释剥离而全命中；
- `async-reset-no-sync` / `missing-async-reg` 因只匹配前缀（`rst*`）而从不命中，
  实际命名是 `rst_n`；
- `for-no-begin` 无法可靠区分漏写 `begin` 与合法的单语句循环体，**删除该规则**。

校准后：84 个 RTL 文件共 163 条命中、**0 条 error 级误报**。

## 阶段八：VCD 波形语义分析

### 新增

- 边沿识别、毛刺型不稳定判定、晚/早一拍相位检查、标准与缺陷 RTL 波形差异、
  失败周期对应的时间窗；接入 Markdown 报告与网页。

### 修复（判据三轮校准）

1. "窗口内翻转多次即不稳定" → 时钟与计数器全面误报；
2. "短于全局中位数 1/3" → `busy` 信号的正常窄脉冲被误报；
3. 最终判据："全局基线 + 连续 ≥3 个异常间隔 + 复位沿不参与统计"。

另修正三处相位检查噪声：裸信号名未解析到 VCD 层次、取"第一个响应沿"而非最小延迟、
多位信号被判成永远不成立的 `unobservable`。

## 阶段七：权威预言机

### 新增

- 内置案例期望值改由确定性参考模型独立复算并**覆盖** AI 数字；AI 期望值偏差单列为
  诊断指标。`AUTHORITATIVE` 门控：只有逐拍对齐的模型才能提供权威期望值。
- 参考模型对齐测试：同组向量同时喂模型与 RTL，多随机种子逐拍比较，要求零差异。

### 修复

- 在线实验曾出现"参考误报 25/40"，根因是 **AI 猜错期望值被同时计入误报与检出**。
  修复后参考误报与期望值不一致双双归零。
- 多周期向量的 `expected` 此前逐周期比对终值，把合法中间状态判成失败；改为只在
  末周期检查。

## 阶段六：离线调试接口

### 新增

- `iverilog_ai.ai.debug_server`：OpenAI 兼容、仅监听回环地址、不联网、无需 API Key，
  使在线代码路径可离线回归。
- provider 支持 `stream="auto"` 三层有界回退（非流式 → 流式 → 流式且不带
  `response_format`）。

## 阶段五：真实模型实验与取证

### 新增

- 固定 / 随机 / 离线 AI / 在线 AI 四策略公平对比脚本与逐次 JSON + Markdown 报告。
- 真实在线模型实验：11 案例、256 次仿真；在线 AI 检出 45/54，显著高于固定 35/54、
  随机 30/54、离线 AI 30/54；计划合法性 100%。

### 记录

- 公开全部 **9 个未检出缺陷**及逐条原因，不只展示最好成绩。
- 记录一次失败尝试：某第三方网关响应不可靠（`output_text` 为空、`IncompleteRead`），
  判定其不能作为可复现实验来源。

## 阶段一至四：确定性验证闭环

### 新增

- `TestPlan` JSON 合约与严格校验、显式 DUT 合约、确定性 testbench 生成器、
  `IVERILOG_AI_RESULT` 结构化记录、失败反例与 Markdown/HTML 报告。
- 无 shell 的受控执行、路径白名单、超时与输出上限。
- Streamlit 单页演示、缺陷基准清单、验证规则包。

### 已知限制（自首版起）

- 仿真通过 **不等于** 可综合；综合通过 **不等于** 时序收敛或能上板；
- 不做时序签核、不做代码覆盖率、不做 CDC 形式化验证；
- 自定义 RTL 不等同于不可信代码安全沙箱。
