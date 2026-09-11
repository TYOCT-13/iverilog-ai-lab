# Icarus 智测核心架构

## 定位

本项目是围绕 Icarus Verilog 的非官方验证扩展。Icarus 与 vvp 是底层
执行引擎，项目自身贡献的是结构化测试计划合约、受控执行器、结果解析、
报告和可复用的生态工作流。项目不修改 Icarus 源码，也不表示获得 Icarus
官方背书。

## 数据流

~~~text
AI/人工测试计划 JSON
          |
          v
TestPlan.from_json()  -- 标识符、数量、类型和范围校验
          |
          v
确定性 testbench 生成器（由上层模块提供）
          |
          v
ExecutionConfig -> SafePathPolicy
          |
          v
iverilog compile -> 独立 run 目录 -> vvp execute
          |
          v
IVERILOG_AI_RESULT {JSON} 行
          |
          v
SimulationResult -> result.json -> Markdown/HTML
~~~

AI 输出只作为测试计划输入。最终通过/失败结论必须来自真实的 Icarus
进程和自检 testbench；没有结构化结果行时，执行器返回 inconclusive，
不会把“进程退出码为零”误报成验证通过。

## 核心模块

- core.models：TestPlan、TestCase、TestStep、ResultRecord 和
  SimulationResult 的无第三方依赖模型。JSON 对象拒绝未知字段，信号名和
  模块名使用安全的 Verilog 标识符规则。
- ai.schema：AI 侧的严格、版本化 `TestPlan`；只允许标量输入/期望值，不
  接受路径、命令或任意 HDL。
- core.contracts：显式 `DutContract`、端口方向/位宽、时钟和复位定义；
  生成器不会从 RTL 或模型输出猜测端口。
- core.testbench：根据计划和合约生成固定 Verilog-2001 testbench，所有检
  查都输出 `IVERILOG_AI_RESULT` 结构化记录；时序向量可显式选择边沿前或
  边沿后采样（`sample_phase`），覆盖状态输出和同沿组合行为。
- core.pipeline：把计划、合约、生成器和 `IcarusExecutor` 串成单次可审计
  流水线，并为失败记录生成稳定指纹和中文反例解释。
- core.config：SafePathPolicy 和 ExecutionConfig。所有 HDL 输入、include
  目录、输出目录都必须位于允许根内；工具只接受 iverilog/vvp basename。
- core.executor：以参数列表调用本机工具，shell 始终关闭；每次运行使用独立
  的临时目录，拥有固定超时和截断后的 stdout/stderr 证据。
- core.report：离线 Markdown/HTML 渲染器。日志和失败字段都会转义，报告
  不加载远端脚本或样式。
- core.cli：`run`、`plan-run`、`compare-rtl`、`report`、`validate-plan` 五个入口，
  适合本地演示与 CI（见 `.github/workflows/ci.yml`）。
- core.toolchain：外部工具探测（`iverilog` / `vvp` / `yosys`）。解析顺序为
  显式参数 → 环境变量（`IVERILOG_PATH` / `VVP_PATH` / `YOSYS_PATH`）→ `PATH` →
  常见安装目录；探测不到返回 `None`，由调用方决定 skip 还是报错，**不猜测路径**。
  测试与 CI 都经它取路径，因此同一套测试在 Windows 与 Linux 上都会真正执行。
- core.synthesis：可选综合证据层（Yosys 独立进程调用）。产出五层证据表，
  未做的层级显式标 `not_run`；**不参与** PASS/FAIL 裁决。
- core.behavior_compare：让两份 RTL 跑同一份 TestPlan，逐检查项与逐波形信号比对。

## 结构化结果协议

自检 testbench 推荐每个断言输出一行：

~~~text
IVERILOG_AI_RESULT {"ok":true,"test_id":"reset","cycle":2}
IVERILOG_AI_RESULT {"ok":false,"test_id":"wrap","cycle":11,
                    "signal":"count","expected":0,"actual":10,
                    "message":"counter did not wrap"}
~~~

前缀后的内容必须是单行 JSON 对象，至少包含布尔 ok。支持的兼容写法是
前缀后使用冒号或等号；普通 display 文本不会被识别。每条 ok=false
记录会生成一个失败反例，包含测试、周期、信号、期望值和实际值。

## 命令

在项目根目录运行：

~~~text
python -m iverilog_ai run --rtl rtl/mod10_counter.v --testbench tb/tb_mod10_counter.v --top tb_mod10_counter
~~~

从显式 JSON 合约执行 AI 计划：

~~~text
python -m iverilog_ai plan-run --plan examples/simple_alu_plan.json \
  --contract examples/simple_alu_contract.json --rtl rtl/simple_alu.v
~~~

默认会在项目根下的 .iverilog-ai/runs 建立独立运行目录，并生成
result.json、compile/run 日志和 report.md。若要从已有结果重新渲染：

~~~text
python -m iverilog_ai report --result .iverilog-ai/runs/run-<id>/result.json --format html --output report.html
~~~

计划验证命令只解析 JSON，不执行 RTL：

~~~text
python -m iverilog_ai validate-plan --plan plans/traffic_light.json
~~~

工具路径可通过 --iverilog、--vvp 指定；在本项目环境中推荐使用
D:\iverilog\bin\iverilog.exe 和 D:\iverilog\bin\vvp.exe。每个进程的 timeout
默认 30 秒，可通过 --timeout 调整但上限为 3600 秒。

## 安全边界

1. 不使用 shell 字符串；模块名、宏定义、include 目录和源文件都经过校验。
2. 允许根默认由 PROJECT_SCOPE.md 所在目录推导；跨目录使用必须显式传入
   --allowed-root。
3. 输出路径会在创建前解析现有父目录，拒绝通过符号链接逃逸。
4. 子进程只继承运行所需的基础环境变量，不转发模型/API 密钥。
5. 不覆盖输入 RTL。自动修复如果加入上层流程，必须在临时副本中验证。
6. 输出过长时保留头尾并在证据中标记截断，避免日志无限占用内存和报告。

## 状态语义

| 状态 | 含义 |
|---|---|
| passed | 编译、执行和至少一条结构化记录全部通过 |
| failed | 编译成功但 vvp 非零退出，或存在 ok=false 记录 |
| compile_failed | iverilog 返回非零或无法启动 |
| timeout | 编译或执行超过受控时限 |
| inconclusive | 没有结果行或结果行损坏，证据不足 |
| configuration_error | CLI 输入或路径策略拒绝执行 |

## 证据与复现

每个 result.json 保存配置、工具命令、源码 SHA-256、返回码、耗时、结构化
记录和工件路径。源码本身不复制到运行目录；报告引用原路径和哈希。提交
缺陷基准时应同时提交 RTL、testbench、期望行为和该 result.json，方便第三方
使用同一版本 Icarus 复现。
