# Icarus 智测流水线报告

> 结论来自本地 iverilog/vvp 进程；AI 解释或自评不是正确性证据。

- 运行 ID：055c90e28fdb
- 运行状态：运行完成（`passed`）
- 设计结果：符合预期（`passed`）
- 证据结论：verified
- 比对情况：9/9 条比对一致
- 开始：2026-09-29T15:17:06.247148Z
- 结束：2026-09-29T15:17:06.316005Z

## 测试覆盖摘要

> 以下是测试计划执行覆盖率，不代表 RTL 代码覆盖率。

- 测试向量：3/3 (100.0%)
- 检查项：9/9 (100.0%)

| 信号 | 覆盖 | 总数 | 百分比 |
|---|---:|---:|---:|
| carry | 3 | 3 | 100.0% |
| result | 3 | 3 | 100.0% |
| zero | 3 | 3 | 100.0% |

## 期望值可信度

- 证据等级：参考模型复算（`reference_model`）
- 参考模型检查：9 项
- 一致：9 项
- 一致率：100.0%

## 多来源交叉验证

- 来源：iverilog, reference_model
- 独立来源数：1
- 交叉结论：`consistent`

## VCD 波形分析

- 时间精度：`0.001 ns`
- 时间范围：`0.0 ns` ～ `3.0 ns`
- 信号数量：14
- 变化总数：37
- 变化记录是否截断：`False`

| 信号 | 位宽 | 变化次数 |
|---|---:|---:|
| `tb_simple_alu.a` | 8 | 3 |
| `tb_simple_alu.b` | 8 | 3 |
| `tb_simple_alu.checks` | 32 | 4 |
| `tb_simple_alu.cycle` | 32 | 4 |
| `tb_simple_alu.dut_i.a` | 8 | 3 |
| `tb_simple_alu.dut_i.b` | 8 | 3 |
| `tb_simple_alu.dut_i.carry` | 1 | 2 |
| `tb_simple_alu.dut_i.extended_result` | 9 | 2 |
| `tb_simple_alu.dut_i.op` | 3 | 3 |
| `tb_simple_alu.dut_i.result` | 8 | 2 |
| `tb_simple_alu.dut_i.zero` | 1 | 2 |
| `tb_simple_alu.failures` | 32 | 1 |
| `tb_simple_alu.op` | 3 | 3 |
| `tb_simple_alu.result` | 8 | 2 |

### 信号活动覆盖率（激励质量）

- 模块：`simple_alu`；信号 7/7 在本次仿真中发生过变化（100%）
- 取值覆盖（信号到达的不同取值 / 类型可能取值）：1%

| 信号 | 到达取值数 | 可能取值数 | 取值覆盖 |
|---|---:|---:|---:|
| `a` | 3 | 256 | 1% |
| `b` | 3 | 256 | 1% |
| `carry` | 2 | 256 | 1% |
| `extended_result` | 2 | 512 | 0% |
| `op` | 3 | 256 | 1% |
| `result` | 2 | 256 | 1% |
| `zero` | 2 | 256 | 1% |

> 本覆盖率是**信号活动覆盖率**（信号在 VCD 中是否变化过），不是语句、分支、条件或翻转覆盖率。Icarus 不提供编译期覆盖率插桩，因此本项目不声称能给出代码覆盖率。信号未变化只表示本次激励没触发它，不等于死代码；信号有变化也不等于对应逻辑被验证。

> 只统计被 $dumpvars 记录的信号；未 dump 的层次不参与统计，也不被算作未覆盖。已排除编译期常量 0 个（它们按定义永不变化，计入会形成假缺口）。取值覆盖只统计已知位宽且位宽 ≤16 的信号，且以「类型可能取值数」为分母——那是理想上限，不是应达目标。

### 波形语义结论

- 未发现不稳定信号或相位偏差。

| 信号 | 归属 | 上升沿 | 下降沿 | 首次跳变(ns) | 稳定性 |
|---|---|---:|---:|---:|---|
| `tb_simple_alu.a` | testbench | 0 | 2 | 0.0 | stable |
| `tb_simple_alu.b` | testbench | 1 | 1 | 0.0 | stable |
| `tb_simple_alu.checks` | testbench | 3 | 0 | 0.0 | stable |
| `tb_simple_alu.cycle` | testbench | 3 | 0 | 0.0 | stable |
| `tb_simple_alu.dut_i.a` | DUT | 0 | 2 | 0.0 | stable |
| `tb_simple_alu.dut_i.b` | DUT | 1 | 1 | 0.0 | stable |
| `tb_simple_alu.dut_i.carry` | DUT | 0 | 1 | 0.0 | stable |
| `tb_simple_alu.dut_i.extended_result` | DUT | 0 | 1 | 0.0 | stable |
| `tb_simple_alu.dut_i.op` | DUT | 2 | 0 | 0.0 | stable |
| `tb_simple_alu.dut_i.result` | DUT | 1 | 0 | 0.0 | stable |
| `tb_simple_alu.dut_i.zero` | DUT | 0 | 1 | 0.0 | stable |
| `tb_simple_alu.failures` | testbench | 0 | 0 | 0.0 | stable |

## 进程证据

### iverilog 编译

- 状态：passed
- 返回码：0
- 用时：43 ms

### vvp 仿真

- 状态：passed
- 返回码：0
- 用时：16 ms

标准输出：

~~~text
VCD info: dumpfile waveform.vcd opened for output.
IVERILOG_AI_RESULT {"ok":true,"test_id":"add_boundary","cycle":0,"signal":"result","expected":"00000000","actual":"00000000"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"add_boundary","cycle":0,"signal":"carry","expected":"1","actual":"1"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"add_boundary","cycle":0,"signal":"zero","expected":"1","actual":"1"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"and_mask","cycle":1,"signal":"result","expected":"00000000","actual":"00000000"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"and_mask","cycle":1,"signal":"carry","expected":"0","actual":"0"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"and_mask","cycle":1,"signal":"zero","expected":"1","actual":"1"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"left_shift","cycle":2,"signal":"result","expected":"00000110","actual":"00000110"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"left_shift","cycle":2,"signal":"carry","expected":"0","actual":"0"}
IVERILOG_AI_RESULT {"ok":true,"test_id":"left_shift","cycle":2,"signal":"zero","expected":"0","actual":"0"}
IVERILOG_AI_SUMMARY {"checks":9,"failures":0,"cycles":3}
~~~

## 失败反例

没有结构化失败反例。

## 工件

- run_dir：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb
- compile_vvp：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb\compile.vvp
- compile_stdout：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb\compile.stdout.txt
- compile_stderr：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb\compile.stderr.txt
- run_stdout：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb\run.stdout.txt
- run_stderr：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb\run.stderr.txt
- vcd：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb\waveform.vcd
- result_json：E:\FPGA_WORK\iverilog-ai-lab\runs\repro-clean\runs\run-055c90e28fdb\result.json

## 执行配置

~~~json
{
  "rtl_path": "E:\\FPGA_WORK\\iverilog-ai-lab\\rtl\\simple_alu.v",
  "testbench_path": "E:\\FPGA_WORK\\iverilog-ai-lab\\runs\\repro-clean\\tb_simple_alu.v",
  "top_module": "tb_simple_alu",
  "output_dir": "E:\\FPGA_WORK\\iverilog-ai-lab\\runs\\repro-clean\\runs",
  "iverilog_path": "D:\\iverilog\\bin\\iverilog.exe",
  "vvp_path": "D:\\iverilog\\bin\\vvp.exe",
  "timeout_seconds": 30.0,
  "allowed_roots": [
    "E:\\FPGA_WORK\\iverilog-ai-lab"
  ],
  "include_dirs": [],
  "defines": [],
  "language": "2012",
  "keep_artifacts": true,
  "rtl_sha256": "3403ba37a604ad014fc5f6a4e540fcc2d26698b63e32b890851e982ca3522153",
  "testbench_sha256": "96ebe556c3ee9ee53428c14af3f46e863d1d08456c7c3918276fe9063f165e97",
  "coverage": {
    "definition": "测试计划执行覆盖率；不代表 RTL 代码覆盖率",
    "vectors": {
      "covered": 3,
      "total": 3,
      "percent": 100.0
    },
    "checks": {
      "covered": 9,
      "total": 9,
      "percent": 100.0
    },
    "per_signal": {
      "carry": {
        "covered": 3,
        "total": 3,
        "percent": 100.0
      },
      "result": {
        "covered": 3,
        "total": 3,
        "percent": 100.0
      },
      "zero": {
        "covered": 3,
        "total": 3,
        "percent": 100.0
      }
    }
  },
  "oracle": {
    "status": "passed",
    "design": "simple_alu",
    "warnings": [],
    "checked": 3,
    "checked_expected": 9,
    "matched_expected": 9,
    "consistency_rate": 1.0,
    "evidence_level": "reference_model",
    "expectation_source": "reference_model",
    "expectation_evidence_level": "reference_model",
    "plans_with_expectations": 3,
    "ai_expectations_used_for_checking": false,
    "authoritative_vectors": 3
  },
  "structured_assertions": {
    "status": "skipped",
    "checked": 0,
    "passed": 0,
    "failed": 0,
    "results": []
  },
  "cross_validation": {
    "sources": [
      "iverilog",
      "reference_model"
    ],
    "independent_sources": 1,
    "status": "consistent",
    "ai_expected_mismatch": false
  },
  "verification_status": "verified",
  "vcd_analysis": {
    "schema_version": "1.0",
    "file": "E:\\FPGA_WORK\\iverilog-ai-lab\\runs\\repro-clean\\runs\\run-055c90e28fdb\\waveform.vcd",
    "sha256": "a1a6a765c0f37ecbbec0824b2b0ca388bbc0d7ad9dfa1ee76691b8b886997082",
    "timescale_ns": 0.001,
    "signal_count": 14,
    "signals": [
      {
        "name": "tb_simple_alu.a",
        "scope": "tb_simple_alu",
        "width": 8,
        "changes": 3,
        "distinct_values": 3
      },
      {
        "name": "tb_simple_alu.b",
        "scope": "tb_simple_alu",
        "width": 8,
        "changes": 3,
        "distinct_values": 3
      },
      {
        "name": "tb_simple_alu.checks",
        "scope": "tb_simple_alu",
        "width": 32,
        "changes": 4,
        "distinct_values": 4
      },
      {
        "name": "tb_simple_alu.cycle",
        "scope": "tb_simple_alu",
        "width": 32,
        "changes": 4,
        "distinct_values": 4
      },
      {
        "name": "tb_simple_alu.dut_i.a",
        "scope": "tb_simple_alu.dut_i",
        "width": 8,
        "changes": 3,
        "distinct_values": 3
      },
      {
        "name": "tb_simple_alu.dut_i.b",
        "scope": "tb_simple_alu.dut_i",
        "width": 8,
        "changes": 3,
        "distinct_values": 3
      },
      {
        "name": "tb_simple_alu.dut_i.carry",
        "scope": "tb_simple_alu.dut_i",
        "width": 1,
        "changes": 2,
        "distinct_values": 2
      },
      {
        "name": "tb_simple_alu.dut_i.extended_result",
        "scope": "tb_simple_alu.dut_i",
        "width": 9,
        "changes": 2,
        "distinct_values": 2
      },
      {
        "name": "tb_simple_alu.dut_i.op",
        "scope": "tb_simple_alu.dut_i",
        "width": 3,
        "changes": 3,
        "distinct_values": 3
      },
      {
        "name": "tb_simple_alu.dut_i.result",
        "scope": "tb_simple_alu.dut_i",
        "width": 8,
        "changes": 2,
        "distinct_values": 2
      },
      {
        "name": "tb_simple_alu.dut_i.zero",
        "scope": "tb_simple_alu.dut_i",
        "width": 1,
        "changes": 2,
        "distinct_values": 2
      },
      {
        "name": "tb_simple_alu.failures",
        "scope": "tb_simple_alu",
        "width": 32,
        "changes": 1,
        "distinct_values": 1
      },
      {
        "name": "tb_simple_alu.op",
        "scope": "tb_simple_alu",
        "width": 3,
        "changes": 3,
        "distinct_values": 3
      },
      {
        "name": "tb_simple_alu.result",
        "scope": "tb_simple_alu",
        "width": 8,
        "changes": 2,
        "distinct_values": 2
      }
    ],
    "start_ns": 0.0,
    "end_ns": 3.0,
    "total_changes": 37,
    "changes": [
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.dut_i.result",
        "value": "0"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.dut_i.extended_result",
        "value": "100000000"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.dut_i.op",
        "value": "0"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.dut_i.b",
        "value": "1"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.dut_i.a",
        "value": "11111111"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.failures",
        "value": "0"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.cycle",
        "value": "0"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.checks",
        "value": "0"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.op",
        "value": "0"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.b",
        "value": "1"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.a",
        "value": "11111111"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.dut_i.carry",
        "value": "1"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.result",
        "value": "0"
      },
      {
        "time_ns": 0.0,
        "signal": "tb_simple_alu.dut_i.zero",
        "value": "1"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.dut_i.carry",
        "value": "0"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.dut_i.extended_result",
        "value": "0"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.op",
        "value": "10"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.dut_i.op",
        "value": "10"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.b",
        "value": "1111"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.dut_i.b",
        "value": "1111"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.a",
        "value": "11110000"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.dut_i.a",
        "value": "11110000"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.cycle",
        "value": "1"
      },
      {
        "time_ns": 1.0,
        "signal": "tb_simple_alu.checks",
        "value": "11"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.dut_i.zero",
        "value": "0"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.result",
        "value": "110"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.dut_i.result",
        "value": "110"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.op",
        "value": "101"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.dut_i.op",
        "value": "101"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.b",
        "value": "0"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.dut_i.b",
        "value": "0"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.a",
        "value": "11"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.dut_i.a",
        "value": "11"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.cycle",
        "value": "10"
      },
      {
        "time_ns": 2.0,
        "signal": "tb_simple_alu.checks",
        "value": "110"
      },
      {
        "time_ns": 3.0,
        "signal": "tb_simple_alu.cycle",
        "value": "11"
      },
      {
        "time_ns": 3.0,
        "signal": "tb_simple_alu.checks",
        "value": "1001"
      }
    ],
    "truncated": false,
    "status": "parsed",
    "insights": {
      "schema_version": "1.1",
      "clock_period_ns": 10.0,
      "dut_scopes": [
        "tb_simple_alu.dut_i"
      ],
      "signal_edges": [
        {
          "signal": "tb_simple_alu.a",
          "rises": 0,
          "falls": 2,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.b",
          "rises": 1,
          "falls": 1,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.checks",
          "rises": 3,
          "falls": 0,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.cycle",
          "rises": 3,
          "falls": 0,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.dut_i.a",
          "rises": 0,
          "falls": 2,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.dut_i.b",
          "rises": 1,
          "falls": 1,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.dut_i.carry",
          "rises": 0,
          "falls": 1,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.dut_i.extended_result",
          "rises": 0,
          "falls": 1,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.dut_i.op",
          "rises": 2,
          "falls": 0,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.dut_i.result",
          "rises": 1,
          "falls": 0,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.dut_i.zero",
          "rises": 0,
          "falls": 1,
          "first_edge_ns": 0.0
        },
        {
          "signal": "tb_simple_alu.failures",
          "rises": 0,
          "falls": 0,
          "first_edge_ns": 0.0
        }
      ],
      "stability": [
        {
          "signal": "tb_simple_alu.a",
          "flips": 2,
          "first_flip_ns": 1.0,
          "last_flip_ns": 2.0,
          "typical_interval_ns": 1.0,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu",
          "is_dut": false
        },
        {
          "signal": "tb_simple_alu.b",
          "flips": 2,
          "first_flip_ns": 1.0,
          "last_flip_ns": 2.0,
          "typical_interval_ns": 1.0,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu",
          "is_dut": false
        },
        {
          "signal": "tb_simple_alu.checks",
          "flips": 3,
          "first_flip_ns": 1.0,
          "last_flip_ns": 3.0,
          "typical_interval_ns": 1.0,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu",
          "is_dut": false
        },
        {
          "signal": "tb_simple_alu.cycle",
          "flips": 3,
          "first_flip_ns": 1.0,
          "last_flip_ns": 3.0,
          "typical_interval_ns": 1.0,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu",
          "is_dut": false
        },
        {
          "signal": "tb_simple_alu.dut_i.a",
          "flips": 2,
          "first_flip_ns": 1.0,
          "last_flip_ns": 2.0,
          "typical_interval_ns": 1.0,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu.dut_i",
          "is_dut": true
        },
        {
          "signal": "tb_simple_alu.dut_i.b",
          "flips": 2,
          "first_flip_ns": 1.0,
          "last_flip_ns": 2.0,
          "typical_interval_ns": 1.0,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu.dut_i",
          "is_dut": true
        },
        {
          "signal": "tb_simple_alu.dut_i.carry",
          "flips": 1,
          "first_flip_ns": 1.0,
          "last_flip_ns": 1.0,
          "typical_interval_ns": null,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu.dut_i",
          "is_dut": true
        },
        {
          "signal": "tb_simple_alu.dut_i.extended_result",
          "flips": 1,
          "first_flip_ns": 1.0,
          "last_flip_ns": 1.0,
          "typical_interval_ns": null,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu.dut_i",
          "is_dut": true
        },
        {
          "signal": "tb_simple_alu.dut_i.op",
          "flips": 2,
          "first_flip_ns": 1.0,
          "last_flip_ns": 2.0,
          "typical_interval_ns": 1.0,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu.dut_i",
          "is_dut": true
        },
        {
          "signal": "tb_simple_alu.dut_i.result",
          "flips": 1,
          "first_flip_ns": 2.0,
          "last_flip_ns": 2.0,
          "typical_interval_ns": null,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu.dut_i",
          "is_dut": true
        },
        {
          "signal": "tb_simple_alu.dut_i.zero",
          "flips": 1,
          "first_flip_ns": 2.0,
          "last_flip_ns": 2.0,
          "typical_interval_ns": null,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu.dut_i",
          "is_dut": true
        },
        {
          "signal": "tb_simple_alu.failures",
          "flips": 0,
          "first_flip_ns": null,
          "last_flip_ns": null,
          "typical_interval_ns": null,
          "window_ns": 10.0,
          "unstable_windows": [],
          "status": "stable",
          "scope": "tb_simple_alu",
          "is_dut": false
        }
      ],
      "phase_checks": [],
      "unstable_signals": [],
      "unstable_auxiliary": [],
      "phase_violations": [],
      "phase_not_applicable": [],
      "notes": [],
      "disclaimer": "波形结论来自 VCD 数值本身，不替代 Icarus 仿真结论，也不等同综合或时序签核。"
    },
    "coverage": {
      "status": "measured",
      "module": "simple_alu",
      "source_lines": {
        "start": 3,
        "end": 24
      },
      "declared_signals": 7,
      "changed_signals": 7,
      "unchanged_signals": 0,
      "ratio": 1.0,
      "unchanged": [],
      "value_coverage": 0.0089,
      "value_detail": [
        {
          "signal": "a",
          "distinct_values": 3,
          "possible_values": 256,
          "ratio": 0.0117
        },
        {
          "signal": "b",
          "distinct_values": 3,
          "possible_values": 256,
          "ratio": 0.0117
        },
        {
          "signal": "carry",
          "distinct_values": 2,
          "possible_values": 256,
          "ratio": 0.0078
        },
        {
          "signal": "extended_result",
          "distinct_values": 2,
          "possible_values": 512,
          "ratio": 0.0039
        },
        {
          "signal": "op",
          "distinct_values": 3,
          "possible_values": 256,
          "ratio": 0.0117
        },
        {
          "signal": "result",
          "distinct_values": 2,
          "possible_values": 256,
          "ratio": 0.0078
        },
        {
          "signal": "zero",
          "distinct_values": 2,
          "possible_values": 256,
          "ratio": 0.0078
        }
      ],
      "excluded_parameters": [],
      "excluded_memories": [],
      "changed_by_instance": {
        "dut_i": [
          "a",
          "b",
          "carry",
          "extended_result",
          "op",
          "result",
          "zero"
        ]
      },
      "note": "只统计被 $dumpvars 记录的信号；未 dump 的层次不参与统计，也不被算作未覆盖。已排除编译期常量 0 个（它们按定义永不变化，计入会形成假缺口）。取值覆盖只统计已知位宽且位宽 ≤16 的信号，且以「类型可能取值数」为分母——那是理想上限，不是应达目标。",
      "disclaimer": "本覆盖率是**信号活动覆盖率**（信号在 VCD 中是否变化过），不是语句、分支、条件或翻转覆盖率。Icarus 不提供编译期覆盖率插桩，因此本项目不声称能给出代码覆盖率。信号未变化只表示本次激励没触发它，不等于死代码；信号有变化也不等于对应逻辑被验证。"
    }
  },
  "synthesis": {
    "status": "not_run",
    "skipped_reason": "未启用综合证据层（run_synthesis=False）"
  }
}
~~~
