# 发布包复现输入清单

公开根目录：`benchmarks/rtl_style_maintenance_20261007/`。下表 private 路径均相对于私有 `candidate-r3/`；复制时必须保持字节一致。完整哈希绑定见 publishable_inputs.json。

除了 35 份必要输入，还需复制入口 publishable_reproduce.py 和绑定清单 publishable_inputs.json。原 623 项证据归档、旧入口和旧回执保持不变。

| Public 路径 | Private 路径 |
| --- | --- |
| `targets/event_accumulator/A/event_accumulator.v` | `attempt-r3/targets/event_accumulator/A/event_accumulator.v` |
| `originals/event_accumulator/A/event_accumulator.v` | `originals/event_accumulator/A/event_accumulator.v` |
| `spec/targets/event_accumulator/A/event_accumulator_spec.md` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/A/event_accumulator_spec.md` |
| `spec/targets/event_accumulator/A/waveforms/event_accumulator_variant-behavior.json5` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/A/waveforms/event_accumulator_variant-behavior.json5` |
| `spec/targets/event_accumulator/A/waveforms/event_accumulator_variant-behavior.svg` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/A/waveforms/event_accumulator_variant-behavior.svg` |
| `targets/event_accumulator/B/event_accumulator.v` | `attempt-r3/targets/event_accumulator/B/event_accumulator.v` |
| `originals/event_accumulator/B/event_accumulator.v` | `originals/event_accumulator/B/event_accumulator.v` |
| `spec/targets/event_accumulator/B/event_accumulator_spec.md` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/B/event_accumulator_spec.md` |
| `spec/targets/event_accumulator/B/waveforms/event_accumulator_variant-behavior.json5` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/B/waveforms/event_accumulator_variant-behavior.json5` |
| `spec/targets/event_accumulator/B/waveforms/event_accumulator_variant-behavior.svg` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/B/waveforms/event_accumulator_variant-behavior.svg` |
| `targets/event_accumulator/C/event_accumulator.v` | `attempt-r3/targets/event_accumulator/C/event_accumulator.v` |
| `originals/event_accumulator/C/event_accumulator.v` | `originals/event_accumulator/C/event_accumulator.v` |
| `spec/targets/event_accumulator/C/event_accumulator_spec.md` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/C/event_accumulator_spec.md` |
| `spec/targets/event_accumulator/C/waveforms/event_accumulator_variant-behavior.json5` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/C/waveforms/event_accumulator_variant-behavior.json5` |
| `spec/targets/event_accumulator/C/waveforms/event_accumulator_variant-behavior.svg` | `diagram-encoding-r1/bundle/spec/targets/event_accumulator/C/waveforms/event_accumulator_variant-behavior.svg` |
| `targets/valid_data_pipeline/A/valid_data_pipeline.v` | `attempt-r3/targets/valid_data_pipeline/A/valid_data_pipeline.v` |
| `originals/valid_data_pipeline/A/valid_data_pipeline.v` | `originals/valid_data_pipeline/A/valid_data_pipeline.v` |
| `spec/targets/valid_data_pipeline/A/valid_data_pipeline_spec.md` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/A/valid_data_pipeline_spec.md` |
| `spec/targets/valid_data_pipeline/A/waveforms/valid_data_pipeline_variant-behavior.json5` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/A/waveforms/valid_data_pipeline_variant-behavior.json5` |
| `spec/targets/valid_data_pipeline/A/waveforms/valid_data_pipeline_variant-behavior.svg` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/A/waveforms/valid_data_pipeline_variant-behavior.svg` |
| `targets/valid_data_pipeline/B/valid_data_pipeline.v` | `attempt-r3/targets/valid_data_pipeline/B/valid_data_pipeline.v` |
| `originals/valid_data_pipeline/B/valid_data_pipeline.v` | `originals/valid_data_pipeline/B/valid_data_pipeline.v` |
| `spec/targets/valid_data_pipeline/B/valid_data_pipeline_spec.md` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/B/valid_data_pipeline_spec.md` |
| `spec/targets/valid_data_pipeline/B/waveforms/valid_data_pipeline_variant-behavior.json5` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/B/waveforms/valid_data_pipeline_variant-behavior.json5` |
| `spec/targets/valid_data_pipeline/B/waveforms/valid_data_pipeline_variant-behavior.svg` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/B/waveforms/valid_data_pipeline_variant-behavior.svg` |
| `targets/valid_data_pipeline/C/valid_data_pipeline.v` | `attempt-r3/targets/valid_data_pipeline/C/valid_data_pipeline.v` |
| `originals/valid_data_pipeline/C/valid_data_pipeline.v` | `originals/valid_data_pipeline/C/valid_data_pipeline.v` |
| `spec/targets/valid_data_pipeline/C/valid_data_pipeline_spec.md` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/C/valid_data_pipeline_spec.md` |
| `spec/targets/valid_data_pipeline/C/waveforms/valid_data_pipeline_variant-behavior.json5` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/C/waveforms/valid_data_pipeline_variant-behavior.json5` |
| `spec/targets/valid_data_pipeline/C/waveforms/valid_data_pipeline_variant-behavior.svg` | `diagram-encoding-r1/bundle/spec/targets/valid_data_pipeline/C/waveforms/valid_data_pipeline_variant-behavior.svg` |
| `verification/spec-input/A.spec.json` | `diagram-encoding-r1/input/A.spec.json` |
| `verification/spec-input/B.spec.json` | `diagram-encoding-r1/input/B.spec.json` |
| `verification/spec-input/C.spec.json` | `diagram-encoding-r1/input/C.spec.json` |
| `verification/public-oracle/job-source.txt` | `validation/public-oracle/job-source.txt` |
| `verification/four-state/job-source.txt` | `validation/four-state/job-source.txt` |

项目原有两个 contract 位于 benchmarks/agent_new_holdout_20261005/contracts/，不复制成新 oracle；其 SHA-256 亦由清单绑定。运行时从脚本目录向上推导项目根，或传 --project-root；使用 sys.executable，skill 安装位置由 --skill-root 给出。

从项目根运行：

```text
python -B -X utf8 benchmarks/rtl_style_maintenance_20261007/publishable_reproduce.py --out-dir .tmp-codex/rtl-style-maintenance-repeat-r1 --mode all --skill-root <installed_readable_verilog_skill_root>
```

--out-dir 必须是新仓库内目录；既存目录、仓库外目录、发布输入目录会被拒绝。模式为 gate/spec/semantics/all；semantics 会先运行官方源码门禁。所有 stdout/stderr/退出码、新生成物和 DUT 统计写入新输出目录。spec 只读取 verification/spec-input/A.spec.json、B.spec.json、C.spec.json，并核对它们与 spec/targets 的最终 WaveJSON 完全一致；不读取旧 final_receipt.json 或原有坏图。

每份语义脚本执行前明确断言八处路径替换：项目根、包根、src 导入、fresh gate 报告、候选源码目录、三处结果目录。其余 AST（包括向量、判据、比较）保持。原件继续取 originals，候选取 targets；原两份 job-source 字节和 SHA-256 保留。

入口完成语法及两组路径替换的零 DUT smoke；帮助检查另存 publishable_help.*。没有在 private 再跑 36 DUT。主代理在公开包实际运行 all 后新增的 36 次必须列为同一组向量的第二次验证，总执行数 72，不能视作新独立样本或 API 实验。
