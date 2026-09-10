"""核心验证运行时及 AI 测试计划流水线公共 API。"""

from .config import (
    ConfigurationError,
    ExecutionConfig,
    ResolvedExecutionConfig,
    SafePathError,
    SafePathPolicy,
)
from .contracts import (
    ClockContract,
    ContractValidationError,
    DUTContract,
    DUTPort,
    DutContract,
    DutPort,
    PortDirection,
    PortSpec,
    ResetContract,
)
from .executor import IcarusExecutor, RESULT_MARKER, SimulationRunner, parse_result_records
from .models import (
    ClockSpec,
    CompileResult,
    FailureRecord,
    ModelValidationError,
    ProcessResult,
    ProcessStatus,
    ResetSpec,
    ResultRecord,
    ResultStatus,
    SimulationResult,
    TestCase,
    TestPlan,
    TestStep,
)
from .pipeline import (
    FailureExplanation,
    PipelineResult,
    PipelineValidationError,
    VerificationPipeline,
    execute_test_plan,
    explain_failure,
    explain_failure_record,
    coverage_summary,
    explain_failures,
    run_test_plan,
    run_plan,
    summarize_failure,
)
from .report import ReportFormat, generate_report, render_html, render_markdown, write_report
from .testbench import TestbenchGenerationError, TestbenchGenerator, generate_testbench
from .rtl_import import ImportedRTL, ImportedRTLProject, RTLImportError, available_modules, extract_contract_draft, import_rtl_bytes, import_rtl_project

__all__ = [
    "ClockContract",
    "ClockSpec",
    "CompileResult",
    "ConfigurationError",
    "ContractValidationError",
    "DUTContract",
    "DUTPort",
    "DutContract",
    "DutPort",
    "ExecutionConfig",
    "FailureExplanation",
    "FailureRecord",
    "IcarusExecutor",
    "ModelValidationError",
    "PipelineResult",
    "PipelineValidationError",
    "PortDirection",
    "PortSpec",
    "ProcessResult",
    "ProcessStatus",
    "RESULT_MARKER",
    "ReportFormat",
    "ResetContract",
    "ResetSpec",
    "ResolvedExecutionConfig",
    "ResultRecord",
    "ResultStatus",
    "SafePathError",
    "SafePathPolicy",
    "SimulationResult",
    "SimulationRunner",
    "TestCase",
    "TestPlan",
    "TestStep",
    "TestbenchGenerationError",
    "TestbenchGenerator",
    "VerificationPipeline",
    "execute_test_plan",
    "explain_failure",
    "explain_failure_record",
    "coverage_summary",
    "explain_failures",
    "generate_report",
    "generate_testbench",
    "parse_result_records",
    "render_html",
    "render_markdown",
    "run_test_plan",
    "run_plan",
    "summarize_failure",
    "write_report",
    "ImportedRTL",
    "ImportedRTLProject",
    "available_modules",
    "import_rtl_project",
    "RTLImportError",
    "extract_contract_draft",
    "import_rtl_bytes",
]


from .reference_model import check_plan_consistency

__all__.append('check_plan_consistency')


from .assertions import AssertionValidationError, StructuredAssertion, AssertionCheckResult, build_assertion, create_assertion, evaluate_assertion
from .waveform import summarize_failure_window, render_failure_window
__all__ += ['AssertionValidationError','StructuredAssertion','AssertionCheckResult','build_assertion','create_assertion','evaluate_assertion','summarize_failure_window','render_failure_window']






from .repair_compare import RepairComparison, compare_simulation_results, safe_candidate_copy
__all__ += ['RepairComparison','compare_simulation_results','safe_candidate_copy']

from .rtl_compare import compare_rtl_sources
__all__ += ['compare_rtl_sources']

from .rules import rule_manifest, rules_context, rules_fingerprint
__all__ += ['rule_manifest', 'rules_context', 'rules_fingerprint']
from .rule_assertions import assertion_suggestions
__all__ += ['assertion_suggestions']
from .static_review import StaticFinding, review_rtl_source, review_rtl_file, render_static_markdown
__all__ += ['StaticFinding', 'review_rtl_source', 'review_rtl_file', 'render_static_markdown']
from .vcd import VCDChange, analyze_vcd_file, analyze_failure_windows
__all__ += ['VCDChange', 'analyze_vcd_file', 'analyze_failure_windows']


