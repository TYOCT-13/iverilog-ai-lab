# 行为级对比：同一份 TestPlan 跑两份 RTL

更新日期：2026-09-10
实现位置：`src/iverilog_ai/core/behavior_compare.py`
测试：`tests/core/test_behavior_compare.py`（5 项）
命令行：`python -m iverilog_ai compare-rtl ...`

## 一、和"结构对比"的分工

项目里有两个 RTL 对比入口，职责不同，不能混为一谈：

| 入口 | 比什么 | 证据强度 |
|---|---|---|
| `rtl_compare.compare_rtl_sources` | **结构级**：端口方向/位宽、是否有复位、时序块用阻塞还是非阻塞、有无 `default`、代码规模等文本特征 | 提示性。它只能指出"写法上可能有问题" |
| `behavior_compare.compare_rtl_behavior` | **行为级**：同一份 TestPlan、同一份 contract，两次真实 Icarus 仿真，再逐检查项、逐波形信号比对 | 可核验。差异来自真实仿真结果 |

结构对比的教学价值在于指出"哪里可能不对"，行为对比才能回答"到底对不对"。

## 二、怎么保证"同一份激励"

- 两侧使用**同一个** `TestPlan` 对象与**同一个** `DutContract` 对象；
- 生成的 testbench 来自同一个确定性生成器，因此两侧测试台逐字节一致；
- 两个子目录 `user/` 与 `reference/` 各自独立，工件、日志、VCD 不互相覆盖；
- 期望值两侧都用内置参考模型的权威复算值（若该设计已对齐），因此"测什么"完全一致。

## 三、结论是怎么判定的

### 逐检查项

比对的键是 `(test_id, signal)`：

- 两侧同键但 `ok` 或 `actual` 不同 → `record` 类型差异；
- 只有一侧有某个键 → `record_missing_in_user` / `record_missing_in_reference`。

键集合理应完全一致（因为 testbench 相同），出现缺失本身就说明有问题（例如一侧编译产出了不同的检查项）。

### 波形

用 `compare_waveforms` 比对共有信号：

- 跳变次数不同 → `edge_count`；
- 跳变时刻不同 → `timing`；
- 跳变时刻一致但数值序列不同 → `value`。

**语义细节（踩过的坑）**：`compare_waveforms` 的 `status` 只描述**共有信号**的可观测行为。一侧多出内部辅助变量（例如把 `counter+1` 提取成 `next_count`）是实现细节，不是行为差异——早期版本会把这种情况判成 `different`，导致"语义等价的重写"被误报。现在：

- `status`：只看共有信号是否一致；
- `same_signal_set` / `only_in_*`：单独表达信号集合差异；
- `behavior_compare` 再区分这些多出的信号是**DUT 内部**（实现细节，不计入差异）还是**端口层面**（影响可用性，必须提示）。

## 四、最终状态

| 状态 | 含义 |
|---|---|
| `identical` | 覆盖范围内逐检查项一致、共有信号波形一致 |
| `different` | 存在检查项差异或 DUT 内部信号波形差异 |
| `records_identical_waveform_unavailable` | 检查项一致，但没有可比的 VCD；如实说明而不是假装一致 |

`identical` 的措辞刻意保守：**只说明测试计划覆盖范围内的行为一致**，不等于实现完全等价、更不等于代码质量相同。报告里同时给出这句限定和"波形差异只描述可观测行为"的免责声明。

## 五、可核验的实测结果

对 PWM 做四种对比（同一份 12 向量计划）：

| 对比对象 | 期望 | 实测 | 关键证据 |
|---|---|---|---|
| 与自己比 | `identical` | ✅ `identical` | 28/28 检查项一致，波形 0 差异 |
| `pwm_bug_inverted_polarity`（极性反转） | `different` | ✅ `different` | 27 处检查项差异；`dut_i.pwm_out` 参考 12 次跳变、用户 11 次 |
| `pwm_bug_off_by_one`（计数差一） | `different` | ✅ `different` | 6 处检查项差异；`dut_i.pwm_out` 跳变数 12 vs 4 |
| 语义等价重写（多出 `next_count`） | `identical` | ✅ `identical` | 0 差异；多出的内部信号被标为"实现细节" |

## 六、命令行用法

```powershell
python -m iverilog_ai compare-rtl `
  --plan .dsh-tmp/pwm_plan.json `
  --contract examples/pwm_contract.json `
  --user-rtl rtl/pwm_bug_inverted_polarity.v `
  --reference-rtl rtl/pwm.v `
  --iverilog D:\iverilog\bin\iverilog.exe `
  --vvp D:\iverilog\bin\vvp.exe
```

输出（节选）：

```json
{
  "status": "different",
  "module": "pwm",
  "user_status": "passed_with_warnings",
  "reference_status": "passed",
  "checks": "12 vs 12",
  "failed": "11 vs 0",
  "mismatched_checks": 11,
  "waveform": "different",
  "dut_waveform_differences": 1
}
```

退出码：`identical` → 0；`different` → 1；无法判定（缺 VCD 等）→ 2。脚本可直接据此判断。

网页端：上传自定义 RTL 后，"结构对比"结果下方会出现「运行行为级对比」按钮（需要先生成 AI 测试计划），结果区展示逐检查项差异表、波形差异与口径说明，并可下载 JSON。

## 七、能力边界（如实说明）

- 只覆盖测试计划激励到的行为；激励没走到的地方，"一致"说明不了任何事；
- 不判定"哪一份是对的"——如果两侧行为不同，需要结合规格或参考模型判断谁错；
- 波形比对只覆盖 VCD 里 dump 出来的信号；`$dumpvars(0, top)` 之外的内部层次不可见；
- 两侧必须能被同一份 contract 实例化；端口不兼容时流水线会先在 testbench 生成阶段失败，而不是给出误导性的行为差异。
