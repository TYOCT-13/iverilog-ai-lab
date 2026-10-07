# 两模块规格波形与渲染原件

日期：2026-10-07。这是固定渲染依赖和规格文档的补充交付，不是新的模型实验。

已安装 WaveDrom 3.6.1，实际 smoke 通过。两个正确 A 版本的 RTL 与原实验逐字节相同；通过技能登记的 `write-spec` 生成同名规格、WaveJSON 和 SVG，并逐张查看浏览器截图。仅缩短渲染输入中两个标题，信号、逐拍数据和其他规格字段不变。

| 模块 | 同名规格 | 矢量图 | 实际浏览器截图 |
|---|---|---|---|
| 事件累计器 | [event_accumulator_spec.md](bundle/spec/targets/event_accumulator/A/event_accumulator_spec.md) | [SVG](bundle/spec/targets/event_accumulator/A/waveforms/event_accumulator_normal-operation.svg) | [PNG](visual/event_accumulator_normal-operation.png) |
| 有效数据流水线 | [valid_data_pipeline_spec.md](bundle/spec/targets/valid_data_pipeline/A/valid_data_pipeline_spec.md) | [SVG](bundle/spec/targets/valid_data_pipeline/A/waveforms/valid_data_pipeline_normal-operation.svg) | [PNG](visual/valid_data_pipeline_normal-operation.png) |

图中各拍表示有效时钟沿后状态，假设第一拍前已完成复位。事件累计器展示使能、保持和清除优先级；流水线展示延迟一拍的输出及 flush 清除。复位脉冲、计数回绕等没有画在这两个正常操作示例中。图来自声明的规格，不是从仿真波形测量所得，不增加旧实验的任务数、检出数或覆盖率。

复现须在本机已有该技能、Node.js 20 以上以及 WaveDrom 3.6.1 的前提下运行。脚本只检查依赖，不安装软件，不调用模型 API；输出必须指定一个尚不存在的仓库内目录。

```powershell
python -B -X utf8 docs/experiment/rtl-spec-rendering-2026-10-07/reproduce_specs.py --out-dir .iverilog-ai/spec-reproduce-local-r1
```

[渲染回执](rendering_receipt.json)绑定输入、SVG及原命令。[原字节复制清单](copy_manifest.json)与[关闭尝试清单](closed_attempts_manifest.json)保留来源；[原始尝试包](closed_attempts.zip)包含缺依赖、工作目录拒绝、标题裁切、不适合的 MuPDF 预览以及失败的样式候选，不用成功版本替换这些记录。

最终浏览器的原始 text 矩形仍含缩进空白，部分矩形提示潜在越界；该诊断原样保存，没有写成“零警告”。实际截图中可见标题、端口与数据均完整。SVG 内部引用齐全，不依赖远程图片。

v3 材料的冻结回执保留在提交 `77d0c2f9d009696def1da895a50b4a69c6345f3d`。它的157项来源中，124项按原路径匹配该提交，12张答辩预览与提交中的公开副本逐字节相同，其余21份本地原件另存于[来源快照包](v3_retained_sources.zip)，映射见[来源绑定](v3_material_snapshot_binding.json)。后续修改索引或清单，不覆盖旧回执，也不声称已经完成异机或干净克隆复现。

原实验六个 RTL 的 r3 严格风格门禁仍记有12项问题；本次两张图不改变该历史结果。已通过的独立样式版本与真实语义验证见[单独报告](../rtl_style_maintenance_2026-10-07.md)。真人试用、H02、硬件时序和外部 CI 均不属于本次渲染验收。

[最终交付清单](delivery_manifest.json)绑定本目录文件及渲染报告；旧渲染回执、输入和原件不改写。
