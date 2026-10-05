# Verilog deliverable gate

Root: `E:\FPGA_WORK\iverilog-ai-lab\.tmp-codex\agent-new-holdout-preparation-20261005\targets`
Delivery ready: `False`
Summary: **12 error(s)**, **0 strict warning(s)**

## Actionable VG findings

<a id="vg-finding-1"></a>
### VG013: Counter-like signal `count_o` should use `cnt_` prefix.
- Status: `failed`
- Severity: `error`
- Location: `file:event_accumulator/A/event_accumulator.v:unknown`
- Evidence:
- node_kind: `verilog_rtl`
- detail: naming.counter
- source_excerpt: `naming.counter`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `mechanical`; human review required: `False`
- Example 1 kind: `verilog`
- Bad example:
```text
naming.counter
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-2"></a>
### VG013: Counter-like signal `count_o` should use `cnt_` prefix.
- Status: `failed`
- Severity: `error`
- Location: `file:event_accumulator/B/event_accumulator.v:unknown`
- Evidence:
- node_kind: `verilog_rtl`
- detail: naming.counter
- source_excerpt: `naming.counter`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `mechanical`; human review required: `False`
- Example 1 kind: `verilog`
- Bad example:
```text
naming.counter
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-3"></a>
### VG013: Counter-like signal `count_o` should use `cnt_` prefix.
- Status: `failed`
- Severity: `error`
- Location: `file:event_accumulator/C/event_accumulator.v:unknown`
- Evidence:
- node_kind: `verilog_rtl`
- detail: naming.counter
- source_excerpt: `naming.counter`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `mechanical`; human review required: `False`
- Example 1 kind: `verilog`
- Bad example:
```text
naming.counter
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-4"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `event_accumulator/A/event_accumulator.v:75`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=event_accumulator/A/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=7; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=event_accumulator/A/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=7; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=event_accumulator/A/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=7; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-5"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `event_accumulator/B/event_accumulator.v:75`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=event_accumulator/B/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=5; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=event_accumulator/B/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=5; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=event_accumulator/B/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=5; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-6"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `event_accumulator/C/event_accumulator.v:75`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=event_accumulator/C/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=9; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=event_accumulator/C/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=9; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=event_accumulator/C/event_accumulator.v:event_accumulator; instance_path=event_accumulator; specialization=default; target=count_o; child_output=event_accumulator.count_o; operation_count=9; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-7"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `valid_data_pipeline/A/valid_data_pipeline.v:89`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=valid_data_pipeline/A/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=valid_data_pipeline/A/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=valid_data_pipeline/A/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-8"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `valid_data_pipeline/A/valid_data_pipeline.v:104`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=valid_data_pipeline/A/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=valid_data_pipeline/A/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=valid_data_pipeline/A/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-9"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `valid_data_pipeline/B/valid_data_pipeline.v:89`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=valid_data_pipeline/B/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=valid_data_pipeline/B/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=valid_data_pipeline/B/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-10"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `valid_data_pipeline/B/valid_data_pipeline.v:104`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=valid_data_pipeline/B/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=valid_data_pipeline/B/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=valid_data_pipeline/B/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-11"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `valid_data_pipeline/C/valid_data_pipeline.v:89`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=valid_data_pipeline/C/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=valid_data_pipeline/C/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=valid_data_pipeline/C/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=data_o; child_output=valid_data_pipeline.data_o; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

<a id="vg-finding-12"></a>
### VG146: 组合逻辑操作锥超过强预算；优先加入流水寄存器、注册标志或预译码，并将复杂 FSM 条件拆为多周期时序步骤。这些修改可能改变可见延迟；若协议延迟不可变化，必须阻断并进行人工架构审查。
- Status: `failed`
- Severity: `BLOCKER`
- Location: `valid_data_pipeline/C/valid_data_pipeline.v:104`
- Evidence:
- node_kind: `verilog_rtl`
- detail: definition_root=valid_data_pipeline/C/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
- source_excerpt: `definition_root=valid_data_pipeline/C/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent`
- How to fix: 修复 evidence 所代表的违规事实，并在修改后重新运行对应 VG 门禁。
- Steps:
  1. 打开 location 指向的文件或结构范围，核对 evidence 与当前源码是否一致。
  2. 按 instruction 修改问题片段，保留模块接口、复位和时序契约。
  3. 重新运行对应 VG 门禁，并检查示例方向是否适用于当前模块。
- Risk: `behavioral`; human review required: `True`
- Example 1 kind: `verilog`
- Bad example:
```text
definition_root=valid_data_pipeline/C/valid_data_pipeline.v:valid_data_pipeline; instance_path=valid_data_pipeline; specialization=default; target=reg_capture_data; child_output=valid_data_pipeline.reg_capture_data; operation_count=4; limit=3; inconclusive_reason=none; loop_presence=absent
```
- Good example:
```text
按当前模块接口、时序和可综合约束重写该片段，并保留可追溯的结构事实。
```
- Example note: 示例表达修改方向，不替代当前模块的接口、时序和综合约束审查。

