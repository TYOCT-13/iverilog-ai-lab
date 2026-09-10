"""Icarus 智测的公共 Python API。

本包是围绕 Icarus Verilog 的非官方扩展。底层仿真结论只接受
``iverilog``/``vvp`` 的真实进程结果；模型生成的测试计划必须先经过
``TestPlan`` 的结构化校验。
"""

from .core.config import ConfigurationError, ExecutionConfig, SafePathError, SafePathPolicy
from .core.executor import IcarusExecutor, SimulationRunner
from .core.contracts import (
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
from .core.pipeline import (
    FailureExplanation,
    PipelineResult,
    PipelineValidationError,
    VerificationPipeline,
    execute_test_plan,
    explain_failure,
    explain_failure_record,
    explain_failures,
    run_test_plan,
    run_plan,
    summarize_failure,
)
from .core.testbench import TestbenchGenerationError, TestbenchGenerator, generate_testbench
from .ai.schema import TestPlan as AITestPlan
from .ai.planner import supplement_tests
from .core.models import (
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

__version__ = "0.1.0"

__all__ = [
    "CompileResult",
    "ClockContract",
    "ClockSpec",
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
    "ProcessResult",
    "ProcessStatus",
    "PipelineResult",
    "PipelineValidationError",
    "PortDirection",
    "PortSpec",
    "ResetSpec",
    "ResultRecord",
    "ResultStatus",
    "SafePathError",
    "SafePathPolicy",
    "SimulationResult",
    "SimulationRunner",
    "ResetContract",
    "TestCase",
    "TestPlan",
    "TestStep",
    "AITestPlan",
    "supplement_tests",
    "TestbenchGenerationError",
    "TestbenchGenerator",
    "VerificationPipeline",
    "execute_test_plan",
    "explain_failure",
    "explain_failure_record",
    "explain_failures",
    "generate_testbench",
    "run_test_plan",
    "run_plan",
    "summarize_failure",
]
