## 这个 PR 做了什么

<!-- 一两句话说明。如果影响可核验结论（基准数字、测试数量、对齐覆盖），请给出前后数字。 -->

## 变更类型

- [ ] 新增基准案例 / 缺陷
- [ ] 新增或修改静态规则
- [ ] 修复工具缺陷
- [ ] 文档
- [ ] 其他

## 自查清单

请逐项确认（**未通过的命令不要勾**）：

- [ ] `python -m pytest -q` 全量通过，且有新增测试覆盖本次改动
- [ ] `python scripts/run_benchmark_matrix.py` 输出为
      `references_total: 14`、`reference_false_positives: 0`、
      `defects_total: 78`、`defects_found: 78`、`inconclusive_runs: 0`
      （若本次改动**有意**变更了这些数字，请在下方"结论变更"里说明）
- [ ] `python scripts/strip_bom.py --check` 通过（源码不含 UTF-8 BOM）

## 项目边界确认

- [ ] 本改动**没有**让 AI 输出参与 PASS/FAIL 裁决
- [ ] 本改动**没有**把模型输出拼进命令、路径或 Verilog 代码
- [ ] 若改动涉及参考模型：该模型已通过与 RTL 的**逐拍对齐**测试，才加入 `AUTHORITATIVE`

## 新增基准内容（如有）

- [ ] 案例已成套提交（RTL + contract + 规格 + 功能/边界 testbench + 参考模型 + 对齐用例）
- [ ] 每个缺陷根因独立，且给得出实跑的检出记录行
- [ ] 不可观测的缺陷**没有**被注册，并已在 PR 中说明原因

## 第三方资源（如有）

- [ ] 未引入第三方代码
- [ ] 新增依赖已同步更新 `THIRD_PARTY.md` 与 `docs/competition/opensource_resource_list.md`
- [ ] 未提交无权再分发的图片、数据集或音视频素材

## 结论变更（如有）

<!-- 如果本次改动改变了基准数字、测试数量、对齐覆盖或其他可核验结论，请在此列出前后对比
     并解释原因。没有变更可留空。 -->

## 关联 Issue

<!-- 如 Fixes #123 -->
