"""Evaluation runner for deterministic routing and live tool-selection cases."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from agent.context import AgentContext
from agent.llm import AnthropicMessagesClient, extract_text
from agent.main_agent.hooks import ToolLoopHooks
from agent.main_agent.intent import intent_tool_categories, route_intent
from agent.main_agent.loop import MAX_TOOL_STEPS, _build_system_prompt, agent_loop
from agent.observability import capture_agent_trace
from agent.tools import MAIN_AGENT_TOOLS, render_anthropic_tools
from evaluation.graders import grade_case
from evaluation.sandbox import EvaluationSandbox
from evaluation.schema import EvalCase, load_cases


def run_case(
    case: EvalCase,
    *,
    repeat: int = 1,
    client: AnthropicMessagesClient | None = None,
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
    cache_write_price_per_million: float | None = None,
    cache_read_price_per_million: float | None = None,
) -> dict[str, Any]:
    with capture_agent_trace(metadata={"case_id": case.case_id, "mode": case.mode, "repeat": repeat}) as trace:
        if case.mode == "router":
            intent = route_intent(case.input)
            result = {
                "status": "completed",
                "intent": intent.kind.value,
                "answer": "",
                "steps": [],
            }
        else:
            result = _run_live_case(case, client=client)
    trace_payload = trace.to_dict()
    grade = grade_case(
        case,
        result=result,
        trace=trace_payload,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
        cache_write_price_per_million=cache_write_price_per_million,
        cache_read_price_per_million=cache_read_price_per_million,
    )
    return {
        "schema_version": "agent_eval_result.v1",
        "case": case.to_dict(),
        "repeat": repeat,
        "result": result,
        "trace": trace_payload,
        "grade": grade,
    }


def run_suite(
    cases: str | Iterable[EvalCase],
    *,
    mode: str | None = None,
    repeats: int = 1,
    client_factory: Callable[[], AnthropicMessagesClient] | None = None,
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
    cache_write_price_per_million: float | None = None,
    cache_read_price_per_million: float | None = None,
) -> list[dict[str, Any]]:
    loaded = load_cases(cases) if isinstance(cases, str) else list(cases)
    selected = [case for case in loaded if mode in (None, "all") or case.mode == mode]
    if not selected:
        raise ValueError(f"no cases selected for mode {mode!r}")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    results: list[dict[str, Any]] = []
    for case in selected:
        for repeat in range(1, repeats + 1):
            client = client_factory() if case.mode == "live" and client_factory else None
            results.append(run_case(
                case,
                repeat=repeat,
                client=client,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
                cache_write_price_per_million=cache_write_price_per_million,
                cache_read_price_per_million=cache_read_price_per_million,
            ))
    return results


def _run_live_case(case: EvalCase, *, client: AnthropicMessagesClient | None) -> dict[str, Any]:
    intent = route_intent(case.input)
    allowed_categories = intent_tool_categories(intent)
    tools = [
        render_anthropic_tools([tool])[0]
        for tool in MAIN_AGENT_TOOLS
        if tool.category in allowed_categories
    ]
    context = AgentContext(
        session_id=f"eval-{case.case_id}",
        history_enabled=False,
        messages=[{"role": "user", "content": case.input}],
    )
    messages = list(context.messages)
    steps: list[dict[str, Any]] = []
    hooks = ToolLoopHooks(context, allowed_categories, {"value": False}, steps, verbose=False)
    sandbox = EvaluationSandbox(case)
    try:
        step_count = agent_loop(
            messages,
            tools=tools,
            handlers=sandbox.handlers(),
            hooks=hooks,
            system=_build_system_prompt(intent),
            max_steps=MAX_TOOL_STEPS,
            client=client,
        )
        status = "max_steps_exceeded" if step_count > MAX_TOOL_STEPS else "completed"
        error = None
    except Exception as exc:
        status = "failed"
        error = {"type": type(exc).__name__, "message": str(exc)}
    answer = ""
    for message in messages:
        if message.get("role") == "assistant":
            text = extract_text(message)
            if text:
                answer = text
    result: dict[str, Any] = {
        "status": status,
        "intent": intent.kind.value,
        "answer": answer,
        "steps": steps,
    }
    if error:
        result["error"] = error
    return result
