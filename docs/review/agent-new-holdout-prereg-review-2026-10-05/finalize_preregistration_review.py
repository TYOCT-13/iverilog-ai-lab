"""Seal the read-only review once completed root evidence is available.

Writes new review/receipt/binding files exclusively; never changes old attempts,
production files or credentials, and never runs a provider or DUT. The eight
evidence closure checks are distinct from the 194 control-flow audit checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from zipfile import ZipFile

sys.dont_write_bytecode = True
REVIEW = Path(__file__).resolve().parent
ROOT = REVIEW.parents[2]
REPORT = ROOT / "docs/review/agent_new_holdout_prereg_review_2026-10-05.md"
VALIDATION = ROOT / "docs/experiment/agent-new-holdout-validation-2026-10-05"
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def write_new(path, data):
    raw = data.encode("utf-8") if isinstance(data, str) else (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)


def main():
    require(not REPORT.exists() and not (REVIEW / "receipt.json").exists(), "refuse to replace an already sealed review")
    checks = []
    values = {}
    spec = importlib.util.spec_from_file_location("held_out_prereg_audit_r2", REVIEW / "audit_preregistration_r2.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    sys.addaudithook(audit.process_guard)
    import scripts.run_agent_new_holdout_study as entry

    def verify(name, callback):
        value = callback()
        checks.append({"name": name, "status": "passed", "kind": "non_DUT_evidence_closure"})
        if value is not None:
            values[name] = value
        print("passed: " + name, flush=True)

    r2 = load(REVIEW / "r2/receipt.json")
    r1 = load(REVIEW / "r1/receipt.json")
    registered = load(REVIEW / "r2/registration.json")
    inputs = load(REVIEW / "r2/audited-artifacts.json")
    full = load(VALIDATION / "r2/receipt.json")
    full_r1 = load(VALIDATION / "r1/receipt.json")
    source = load(VALIDATION / "r2/source_fingerprint_after.json")
    package = load(REVIEW / "byte_snapshot_packaging.json")
    style_path = ROOT / "benchmarks/agent_new_holdout_20261005/validation/style/r3/deliverable_gate.json"
    style = load(style_path)

    def original_candidate():
        current = entry.preregister_new_holdout(require_frozen=True)
        require(current == registered, "registered candidate or base HEAD changed after the mechanical audit")
        require(all(sha(ROOT / name) == item["sha256"] for name, item in inputs.items()), "audited input original changed")
        require(len(inputs) == 458 and len(load(entry.MANIFEST)["members"]) == 400, "candidate closure differs")
        require(current["internal_controlled_module_set_holdout"] is True and "same-team" in current["independent_holdout_meaning"], "holdout meaning differs")
        return {"manifest_members": 400, "registered_originals": 458, "source_revision_is_candidate_base_HEAD": current["study"]["source_revision"],
                "current_git_worktree_clean": not bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
                "new_live_output_exists": entry.OUTPUT.exists()}
    verify("seal.final_candidate_unchanged", original_candidate)

    def prior_attempts():
        require(r2["unique_checks"] == r2["non_DUT_checks"] == r2["passed"] == 194 and r2["failed"] == r2["skipped"] == 0, "independent mechanical outcome differs")
        require(r1["passed"] == 0 and r1["failed"] == 1, "original infrastructure failure was hidden")
        require(sha(REVIEW / "audit_preregistration.py") == r1["tool_sha256"] and sha(REVIEW / "audit_preregistration_r2.py") == r2["tool_sha256"], "attempt tool original changed")
        for attempt in ("r1", "r2"):
            for relative, item in load(REVIEW / attempt / "attempt-artifacts-sha256.json").items():
                require(sha(REVIEW / attempt / relative) == item["sha256"], "preserved attempt artifact changed")
        return {"r1_infrastructure_failed": 1, "r2_distinct_non_DUT_passed": 194}
    verify("seal.independent_attempts_originals", prior_attempts)

    def full_originals():
        for attempt, receipt in (("r1", full_r1), ("r2", full)):
            for item in receipt["artifacts"]:
                path = VALIDATION / attempt / item["path"]
                require(sha(path) == item["sha256"] and path.stat().st_size == item["bytes"], "root validation original changed")
        require(full["changed_inputs"] == [] and full_r1["pytest"]["failures"] == 10 and full_r1["passed"] == 2017, "root first failure or final source stability misrepresented")
        require(full["api_requests"] == 0 and full["human_trial"] is False and full["H02_human_review"] is False, "validation scope overstated")
        return {"root_r1_passed": 2017, "root_r1_failed": 10, "root_r1_skipped": 2, "root_r2_originals_sha_valid": True}
    verify("seal.root_validation_originals_and_r1_failures", full_originals)

    def full_outcome():
        suites = list(ET.parse(VALIDATION / "r2/pytest.xml").getroot().iter("testsuite"))
        totals = {key: sum(int(suite.attrib.get(key, "0")) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
        require(totals == full["pytest"] == {"tests": 2035, "failures": 0, "errors": 0, "skipped": 2}, "root XML and receipt disagree")
        require(full["passed"] == 2033 and all(item["exit_code"] == 0 for item in full["commands"]), "root command outcome differs")
        require("2033 passed, 2 skipped" in (VALIDATION / "r2/pytest.log").read_text(encoding="utf-8"), "root pytest stdout outcome missing")
        require("Success: no issues found in 88 source files" in (VALIDATION / "r2/mypy.log").read_text(encoding="utf-8"), "root mypy outcome missing")
        return {"root_pytest": totals, "root_passed": 2033, "root_mypy_sources": 88, "not_counted_as_auditor_executed_pytest": True}
    verify("seal.root_xml_stdout_and_mypy", full_outcome)

    def stable_source():
        require(source == load(VALIDATION / "r2/source_fingerprint_before.json"), "root before/after fingerprints differ")
        require(len(source) == 535 and all(sha(ROOT / name) == value for name, value in source.items()), "root validated source original no longer matches")
        return {"root_fingerprinted_files": 535, "same_current_bytes": True}
    verify("seal.root_final_source_matches_current_bytes", stable_source)

    def archive():
        path = REVIEW / package["archive"]
        require(sha(path) == package["archive_sha256"] and path.stat().st_size == package["archive_bytes"], "snapshot archive bytes differ")
        with ZipFile(path) as zipped:
            require(zipped.testzip() is None, "snapshot ZIP CRC failed")
            require(set(zipped.namelist()) == {item["entry"] for item in package["members"]} and len(package["members"]) == 459, "ZIP member closure differs")
            for item in package["members"]:
                raw = zipped.read(item["entry"])
                require(hashlib.sha256(raw).hexdigest() == item["sha256"] and len(raw) == item["bytes"], "ZIP original SHA/size differs")
                require(raw == (REVIEW / "r2/byte-snapshot" / item["entry"]).read_bytes(), "ZIP differs from preserved local original copy")
        return {"archive_sha256": package["archive_sha256"], "bytes": package["archive_bytes"], "CRC_and_every_original_SHA_independently_verified": True, "members": 459}
    verify("seal.public_zip_crc_members_and_original_bytes", archive)

    def style_failure():
        require(style["delivery_ready"] is False and style["errors"] == 12 and style["delivery_issues_by_rule"] == {"VG013": 3, "VG146": 9}, "strict style failure misrepresented")
        matrix = {name: item["status"] for name, item in style["checks"].items()}
        require(set(matrix) == {"compile", "ast", "readability", "comment", "naming", "profile", "testbench", "toolchain"}, "public skill matrix incomplete")
        renderer = load(ROOT / "benchmarks/agent_new_holdout_20261005/validation/style/r3/renderer-runtime.stdout.txt")
        require(renderer["ok"] is False and "wavedrom@3.6.1" in renderer["missing"], "renderer failure misrepresented")
        return {"matrix": matrix, "delivery_ready": False, "VG013": 3, "VG146": 9, "WaveDrom_renderer_missing": "wavedrom@3.6.1"}
    verify("seal.style_matrix_and_renderer_failure", style_failure)

    def old_accounting():
        old = r2["details"]["history.five_original_preregs_and_accounting_only"]
        for item in old["old_prereg_module_membership_only"]:
            require(sha(ROOT / item["public_prereg_path"]) == item["sha256"], "prior module membership registration changed")
            require(set(item["module_set"]).isdisjoint(audit.CASES), "new controlled modules overlap prior membership")
        for item in old["accounting_only"]:
            base = ROOT / ".iverilog-ai" / item["batch"]
            require(sha(base / "token_budget.json") == item["journal_sha256"] and sha(base / "results.json") == item["results_sha256"], "old accounting original changed")
            require(item["finished_at"] and item["pending_requests"] == 0 and item["historical_usage_charged_to_this_batch"] is False, "old closure changed")
        return {"five_preregs_and_ledgers_unchanged": True, "actual_unknown_requests": sum(item["unknown_usage_requests"] for item in old["accounting_only"]), "charged_against_new_cap": False}
    verify("seal.five_historical_originals_remain_closed", old_accounting)

    require(len(checks) == 8, "expected eight distinct evidence closure checks")
    head = registered["study"]["source_revision"]
    origins = {name: {"sha256": sha(ROOT / name), "size_bytes": (ROOT / name).stat().st_size} for name in sorted(set(inputs) | set(source))}
    table_names = ("scripts/run_agent_new_holdout_study.py", "spec/agent_new_holdout_study_1m_v8.json", "benchmarks/agent_new_holdout_20261005/manifest.json",
                   "docs/experiment/agent_new_holdout_study_plan_2026-10-05.md", "src/iverilog_ai/core/reference_model.py")
    sha_rows = "\n".join(f"| `{name}` | `{origins[name]['sha256']}` |" for name in table_names)
    matrix = values["seal.style_matrix_and_renderer_failure"]["matrix"]
    matrix_rows = "\n".join(f"| `{name}` | `{matrix[name]}` |" for name in ("compile", "ast", "readability", "comment", "naming", "profile", "testbench", "toolchain"))
    history = r2["details"]["history.five_original_preregs_and_accounting_only"]["accounting_only"]
    history_rows = "\n".join(f"| `{item['batch']}` | {item['tokens']['reported_tokens']} | {item['unknown_usage_requests']} | {item['pending_requests']} | `{item['finished_at']}` |" for item in history)
    report = f"""# v8 新内部合成模块集合留出：非实施者事前机器复核

本次候选的登记、控制流与原件闭合机械复核通过：独立 r2 的 194 个唯一非 DUT 检查全部通过；最后另有 8 个不同的证据封装/指纹检查通过，共 202 个唯一成功检查。所有尝试合计 203 个不同检查身份，其中审计 r1 的一个基础设施检查失败保留。复核者未实现本轮 Agent、资产或入口；这是同团队机器复核，不是真人审查，也不满足 H02。

结论限于本次内部受控实验的事前登记条件。当前工作树尚未提交并清洁，不能立即执行 API。主任务须先把最终候选和证据提交到 Git，再重新登记得到实际执行 commit 的 `source_revision`，保持注册字节一致、输出目录全新、旧账 closed，并显式提供本机密钥文件。审核过程中实际 API 请求、真实凭据读取、DUT/Icarus 执行均为零。

## 候选与原字节绑定

审核记录的 `source_revision` 为 `{head}`，它是候选基点 HEAD，不能被描述为已提交的本轮候选。Agent、helper 和导入的 SYSTEM_PROMPT 另锚定于 `a96933786c17986a739fc2da515db3294d6e8044`。当前原字节与该锚定 Git blob 均已真实核对，SYSTEM 是实际 Python 导入后的值。

| 原件 | SHA-256 |
| --- | --- |
{sha_rows}
| `src/iverilog_ai/ai/agent.py`（当前与锚定 Git blob） | `{audit.PINNED['src/iverilog_ai/ai/agent.py']}` |
| `src/iverilog_ai/core/observation_feedback.py`（当前与锚定 Git blob） | `{audit.PINNED['src/iverilog_ai/core/observation_feedback.py']}` |
| 导入后 `SYSTEM_PROMPT` 的 UTF-8 字节 | `{audit.SYSTEM_SHA}` |

全部 400 个正式资产成员、458 个登记源码/输入原件逐个 SHA 与大小见 [audit 原件清单](agent-new-holdout-prereg-review-2026-10-05/r2/audited-artifacts.json)。全部注册 Python 源码、共享执行器、token budget、summary、入口/config/计划、新测试、`.gitattributes` 及两个新资产目录均被登记。根任务全仓 r2 的 535 文件指纹在前后相同，最后再次核对为当前同字节；它覆盖登记之外本轮修正的旧测试。所有公开复核产物与引用证据原字节另外绑定于 [artifact-bindings.json](agent-new-holdout-prereg-review-2026-10-05/artifact-bindings.json)。

真实 `freeze_registered_inputs` 把 458 个输入原字节复制并逐个比较相等，不转换换行。本机 `r2/byte-snapshot/` 原件仍保留，散副本由本机 `.git/info/exclude` 排除重复提交；公开 [byte_snapshot.zip](agent-new-holdout-prereg-review-2026-10-05/byte_snapshot.zip) 含 458 个副本和一个 manifest 共 459 项，SHA `{package['archive_sha256']}`，{package['archive_bytes']} 字节。root 的 [独立封装回执](agent-new-holdout-prereg-review-2026-10-05/byte_snapshot_packaging.json) 和本审核最终检查均验证 ZIP CRC、全成员集合、各成员 SHA/大小与本机原copy相等。synthetic-history 下伪账本属于新审计 fixture，与真实根 `.iverilog-ai/` 无关。

## 实验范围与实跑机械证据

两模块 `valid_data_pipeline`、`event_accumulator`，每个 reference/B/C × 三重复 × 六策略，108 个唯一任务。每策略固定 12 个缺陷任务（四不同缺陷各重复三次）和 6 个正确控制；理论 API 请求上限 126。任务/额度失败或未执行均保留分母。每任务累计 stimulus 24 拍、每 proposal ≤12 vector、累计接受 ≤64 vector；自动两拍复位和正确 RTL audit 单独计数。每次实际 episode 都须新 DUT/自动复位，不承接前一 episode 状态。

实际非 DUT 检查覆盖配置全部范围/pin 漂移、manifest 闭合成员与资源 hash/路径/固定目标、原字节漂移、注册分母与轮转、baseline 只读取正确规格且由 contract/seed 决定、五旧账闭合、snapshot 原字节相等，以及共享执行器在坏 hash 时先拒绝、没有创建 output。UNFROZEN、旧 output、缺显式 key、脏 Git、未跟踪输入、revision/hash 漂移、pending/未完成旧账均拒绝在真实 key/provider/output 之前。

新 Oracle 固定 `i_clk`/`i_rstn`，10 ns/posedge，异步低有效复位两拍，空参数及完整精确端口。两设计各 15 类错误合约（wrong width/signed/extra port/direction、参数、clock/reset 名称/时长/极性/同步性等）均拒绝；before、X/Z、clock 驱动、未知端口、name-only/raw contract 不获得新权威值。手写 pipeline 的捕获/输出/气泡/flush/reset 表与 counter 的许可/clear/mod16/reset 表真实比较通过。既有 17 模型用锚定版本逐个比较：每模块 60 向量，逐拍与 vector_end（typed/dict/无 contract）一致；这项是纯 Python 比较，不是新增 DUT 运行。

30 组 stub Agent 控制流：两 case × single/feedback/no_feedback × 格式拒绝修复、计划预算拒绝修复、格式全拒绝、三轮、提前反例停止。single 的格式/计划拒绝用掉其唯一请求；feedback/no_feedback 拒绝与有效 proposal 共享三个请求，最多三个实际 stub round。所有 no_feedback 状态的 `observation`、`plan_error`、`latest_decision_error` 均为 None；feedback 正控制能看到相应诊断/观察。API state 仅含正确公开规格/contract、允许输入、当前计划、所准许反馈与剩余额度，不含 RTL、目标/变体路径、私有 witness/metadata、旧成绩或源码摘要。stub 管道输出不构成检测率或真实仿真成绩；executor 提前停止和自身剩余额度仍是消融的事实限界。

最终传输 body/入口 factory 实跑机械核对 `https://api.deepseek.com`、`deepseek-flash`、chat_completions、thinking disabled、非 stream、store false、60 秒、max_tokens 4096/force_output_limit。以连接中断、超时、429 与空输出的假 `_request` 验证一次尝试、自动 transport retry 0，未发送网络请求。独立预算为输入+输出 1,000,000 token；付费拒绝计入 usage，cache 字段不叠加，missing usage 保留完整 reservation，不能预留时拒绝。预算不是货币费用估计。

| 执行者/尝试 | 实际结果 | 计数边界 |
| --- | --- | --- |
| 本非实施者审计 r1 | 0 pass / 1 基础设施 fail | Windows audit hook 误拒绝 executable=None 的合法 Git；原件保留 |
| 本非实施者审计 r2 | 194 pass / 0 fail / 0 skip | 194 唯一非 DUT 机械 check |
| 本非实施者最终封装检查 | 8 pass / 0 fail | 8 不同证据/hash/CRC check；不与上项重复 |
| entry 实施者准备 | 55 pytest pass；mypy 1 源零错 | 原 UNFROZEN 准备证据，不能冒充最终冻结验收 |
| asset 实施者 public integration r1 | 76 pass / 28 fail | 误用 failure_count、混淆 failed_checks 与执行器 FAILED；原件保留 |
| asset 实施者 public integration r2 | 104 pass / 0 fail / 0 skip；mypy 3 源零错 | 既有真实 Icarus 功能证据，不是审核者自己执行 |
| root 全仓 r1 | 2017 pass / 10 fail / 2 skip；mypy 88 源零错 | 旧测试路径/新 probe 适配不足；原失败日志保留 |
| root 全仓 r2 | 2033 pass / 0 fail / 2 skip（2035 total）；mypy 88 源零错 | 实际 XML/stdout/exit code 与当前 535 文件指纹已核对 |

各执行者和尝试不能累加成唯一全仓测试数。root 的两个 skip 原因是 Windows 目录符号链接权限 1314、现有推荐断言表为空；没有把 skip 当 pass，也没有声称跨机 clean-clone 复现。独立 [r1 回执](agent-new-holdout-prereg-review-2026-10-05/r1/receipt.json)、[r2 回执](agent-new-holdout-prereg-review-2026-10-05/r2/receipt.json) 与各原 stdout 均保留；root [全仓 r1](../experiment/agent-new-holdout-validation-2026-10-05/r1/receipt.json)、[全仓 r2](../experiment/agent-new-holdout-validation-2026-10-05/r2/receipt.json) 单列引用。

## 五旧批次：仅模块集合及账闭合

只把这五份 public prereg 的 case 集合用于证明内部受控模块集合互斥；旧成绩不用于挑选设计、变体、baseline、输入或结论。`valid_data_pipeline` 与 `event_accumulator` 与五个集合均不相交。旧 results 仅投影 finished_at，旧 token journal 经 TokenBudget 构造校验与 totals 复算；原 journal/results SHA、原 totals 与完整 unknown record 见 r2 回执的 history/accounting 字段。

| 旧批次 | 原 reported tokens | unknown 请求 | pending | 原 finished_at |
| --- | --- | --- | --- | --- |
{history_rows}

五账均真实 present、finished、pending=0，实际 unknown usage 均为 0。不能据此把 future unknown 当零：另外实跑伪账 fixture 验证 unknown 保留 reservation/totals，pending/未完成/缺账/伪零 totals 均拒绝；历史用量从不扣新 1M 独立额度，也不复跑旧 v8 token_budget 失败任务。

## 八个公开 RTL gate 与事实限界

下表来自已封存的 strict [style r3 原报告](../../benchmarks/agent_new_holdout_20261005/validation/style/r3/deliverable_gate.json)，是来源证据引用，不是本审核再跑 formatter 或 DUT。

| public gate | 原报告状态 |
| --- | --- |
{matrix_rows}

`delivery_ready=false`，12 问题是 VG013 命名 3 项、VG146 组合源锥 9 项；这些事实与此前 style r1/r2 失败均原件保留。compile/ast 的 passed 是 formatter 静态证据，不等于 simulator/synthesis/硬件验证。testbench/toolchain 的 not_requested 不改写成通过；实施者和 root 的真实 Icarus 功能证据另外列出。WaveDrom 固定依赖 wavedrom@3.6.1 缺失，renderer check 与注册 write-spec 均失败，未安装依赖，没有成功 SVG 的声明。

内部合成设计与四个语义变体由同团队制作；`independent_holdout=true` 在此只表示五个此前受控 API 批次的模块集合不相交，已明确 `internal_controlled_module_set_holdout=true`、external_independent_holdout=false 及 meaning。不能据此推断外部盲测、独立缺陷作者、预训练未见、外部泛化、显著性、因果增益或真人/H02。本轮 API 之前固定集合可由本地冻结/准入证据描述，但没有独立时间戳支持“在 v8 outcomes 之前选择”的断言。此时无新批次 API 成绩，也不把准备验证或 stub 结果当 AI 增益。

审查未发现需修改生产源码才能通过本轮登记/机械条件的差异。执行前仍须由 root 完成 committed/clean 的准入与新 commit 的重新登记；本审查不代替这一运行时门禁，也不把未通过的 strict RTL 交付门禁变为通过。
"""
    write_new(REPORT, report)
    public_files = {}
    for path in sorted(REVIEW.rglob("*")):
        if not path.is_file() or path.is_relative_to(REVIEW / "r2/byte-snapshot"):
            continue
        public_files[path.relative_to(ROOT).as_posix()] = {"sha256": sha(path), "size_bytes": path.stat().st_size}
    public_files[REPORT.relative_to(ROOT).as_posix()] = {"sha256": sha(REPORT), "size_bytes": REPORT.stat().st_size}
    evidence = {path.relative_to(ROOT).as_posix(): {"sha256": sha(path), "size_bytes": path.stat().st_size}
                for path in sorted(VALIDATION.rglob("*")) if path.is_file()}
    binding = {"schema": "new-holdout-prereg-review-original-byte-bindings-v1", "created_at": datetime.now(timezone.utc).isoformat(),
               "registered_originals": inputs, "final_source_fingerprint_originals": origins, "public_review_artifacts": public_files,
               "root_validation_evidence_originals": evidence, "snapshot_archive_originals": package,
               "note": "this bindings file and final receipt are excluded from their own hashes; final receipt binds this file and report"}
    write_new(REVIEW / "artifact-bindings.json", binding)
    receipt = {"schema": "agent-new-holdout-prereg-review-final-v1", "finished_at": datetime.now(timezone.utc).isoformat(),
               "reviewer": "non-implementer same-team machine reviewer", "human_review": False, "H02": False,
               "scope": "internal controlled synthetic module-set holdout preregistration only", "verdict": "mechanical_and_evidence_checks_passed_pending_committed_clean_execution_admission",
               "source_revision": head, "source_revision_meaning": "candidate base HEAD; not claimed to be an already committed candidate",
               "agent_frozen_from_revision": audit.AGENT_REVISION, "registered_rows": 108, "registered_originals": 458, "manifest_members": 400,
               "final_successful_unique_non_DUT_checks": 202, "independent_control_flow_checks": 194, "distinct_final_evidence_closure_checks": 8,
               "historical_attempt_infrastructure_failures": 1, "all_attempts_distinct_check_identities": 203,
               "actual_API_calls": 0, "real_credential_reads": 0, "actual_DUT_runs": 0,
               "root_pytest_executed_by_reviewer": False, "root_passed": 2033, "root_skipped": 2, "root_failed": 0,
               "root_mypy_sources": 88, "style_delivery_ready": False, "WaveDrom_svg_ready": False,
               "final_evidence_checks": checks, "details": values,
               "artifact_bindings": {"path": "artifact-bindings.json", "sha256": sha(REVIEW / "artifact-bindings.json")},
               "review_report": {"path": REPORT.relative_to(ROOT).as_posix(), "sha256": sha(REPORT)},
               "finalize_tool_sha256": sha(Path(__file__).resolve())}
    write_new(REVIEW / "receipt.json", receipt)
    print(json.dumps({"verdict": receipt["verdict"], "successful_unique_non_DUT_checks": 202, "report_sha256": sha(REPORT), "receipt_sha256": sha(REVIEW / "receipt.json")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
