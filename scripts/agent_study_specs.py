"""Pure rendering of shared short-budget specifications for the Agent study.

The public source specs remain unchanged. This profile combines budget clarity,
independent-episode reminders and protocol priorities; it is not a single-factor
intervention or an independent held-out protocol specification.
"""
from __future__ import annotations


STUDY_SPEC_PROFILE = "short-budget-protocol-priority-combined-v1"

OLD_BUDGET_PREFIX = {
    "sync_fifo": "- 已验证累计激励预算为 **160 周期**",
    "uart_tx": "累计激励周期上限为 **512**",
    "spi_master": "- 本轮累计激励周期上限 **384**",
    "handshake_stage": "- 本轮多轮共享累计激励预算 **160 周期**",
}

_PROTOCOL_PRIORITIES = {
    "sync_fifo": (
        "Prioritize accepted writes that fill the declared DEPTH, an additional write at full "
        "to observe rejection, and accepted reads that check retained data order. Choose your "
        "own legal values and operation grouping. Keep the original pre-edge acceptance and "
        "simultaneous-operation rules; do not infer acceptance merely from an attempted input."
    ),
    "uart_tx": (
        "Prioritize an actual accepted transmission and observation of a complete frame through "
        "busy release, using the original E0 through E40 timing when the remaining budget can "
        "contain it. Idle-only or reset-only observations do not establish transmitted-frame "
        "behavior. Choose your own legal data and bounded additional protocol probes."
    ),
    "spi_master": (
        "Prioritize an accepted request, its completion, and the following idle recovery using "
        "the original E0 through E16 timing when the remaining budget can contain it. Observe "
        "the declared waveform and completion behavior. Choose your own legal data and bounded "
        "additional probes; this remains the described teaching interface, not a full SPI certification."
    ),
    "handshake_stage": (
        "Prioritize accepted input, backpressure holding, and downstream consumption. Use the "
        "original pre-edge valid/ready acceptance rules and distinguish held output from an "
        "input attempt. Choose your own legal values and operation grouping; ordinary upstream "
        "traffic must hold its blocked valid/data until accepted."
    ),
}


def _without_old_budget(case: str, original: str) -> str:
    """Delete one identified budget paragraph, preserving all other source text."""
    prefix = OLD_BUDGET_PREFIX[case]
    lines = original.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError("expected exactly one old budget paragraph")
    first = matches[0]
    end = first + 1
    if prefix.startswith("- "):
        # A wrapped Markdown list item continues only on indented, nonblank lines.
        while end < len(lines) and lines[end].strip() and lines[end].startswith(("  ", "\t")):
            end += 1
    else:
        # UART's budget is a standalone prose paragraph, possibly line-wrapped.
        while (end < len(lines) and lines[end].strip()
               and not lines[end].startswith(("#", "- ", "* ", "+ "))):
            end += 1
    return "".join(lines[:first] + lines[end:])


def render_study_spec(case: str, cycles: int, original: str) -> str:
    """Return one strategy-neutral case spec without reading or writing files.

    ``cycles`` is the cumulative stimulus cap for the task, not a per-episode
    allowance. API groups must receive the same result for the same case/cap.
    Missing or duplicate old budget paragraphs fail closed rather than leaving
    conflicting budget instructions in the prompt.
    """
    if not isinstance(case, str) or case not in OLD_BUDGET_PREFIX:
        raise ValueError("case must be one of the four supported study modules")
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1:
        raise ValueError("cycles must be a positive integer")
    if not isinstance(original, str) or not original:
        raise ValueError("original specification must be nonempty text")
    body = _without_old_budget(case, original)
    prefix = (
        "# Shared short-budget verification study\n\n"
        f"The cumulative stimulus limit for this task is {cycles} cycles across all executed "
        "episodes. The executor controls the remaining cycle, request and round budgets through "
        "execution state. Obey max_new_cycles, remaining_stimulus_cycles, remaining_rounds, "
        "max_new_vectors and any stated request cap. Do not invent additional requests or treat "
        "the cumulative cap as a fresh allowance in every episode.\n\n"
        "Each permitted episode is independent: the contract automatically resets a fresh DUT "
        "before it; earlier vectors, input levels and circuit state are not continued or replayed. "
        "The automatic initial reset is outside stimulus accounting; any manually proposed reset "
        "vectors count toward the cumulative cap. Within an episode, omitted inputs hold their "
        "last driven levels. Use sample_phase=after and known binary input values; the executor "
        "checks each held-input cycle after its edge. Never drive the automatically generated clock.\n\n"
        "The scenario lists below describe the wider regression scope. Choose a focused subset "
        "that fits the remaining cumulative budget; they do not require every scenario in one "
        "episode or all scenarios in this task. Compute the sum of proposed vector cycles privately "
        "and keep it within max_new_cycles. Further proposals or a stop remain subject to the "
        "executor's current request and round limits.\n\n"
        "The decision JSON has exactly the existing top-level action, reason and vectors fields. "
        "Do not add vector_count, total_cycles, cycle_sum or other statistics at the top level. "
        "Each vector retains its cycles field and the existing decision schema. Do not supply "
        "expected outputs, executable content, new oracle rules or fabricated coverage claims; "
        "the executor owns the reference model and observed evidence.\n\n"
        f"Protocol-operation priority for this case: {_PROTOCOL_PRIORITIES[case]}\n\n"
        "Study disclosure: the short-budget scope, episode/sampling reminders and generic protocol "
        "priorities form a combined prompt optimization reused across all API groups for this case. "
        "This development-set comparison does not identify a single-factor causal effect or "
        "establish held-out generalization.\n\n"
        "The original interface, acceptance rules and detailed timing below remain unchanged.\n\n"
    )
    if "\r\n" in original:
        prefix = prefix.replace("\n", "\r\n")
    return prefix + body
