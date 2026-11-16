"""The LangGraph StateGraph: a fixed flow with one bounded retry (ADR 0001).

validate -> fetch_metrics -> plan_news -> collect_news -> synthesize -> verify -> render -> finalize
The only cycle is verify -> synthesize (at most one retry). LLM nodes have no tools.
"""

from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from srag_sentinel.agent.deps import AgentDeps
from srag_sentinel.agent.nodes import build_nodes
from srag_sentinel.agent.state import MAX_SYNTHESIS_ATTEMPTS, ReportState

RECURSION_LIMIT = 25


def _after_validate(state: ReportState) -> str:
    return "finalize" if state.rejected else "fetch_metrics"


def _after_verify(state: ReportState) -> str:
    needs_retry = (
        state.narrative is not None
        and not state.verified
        and state.synthesis_attempts < MAX_SYNTHESIS_ATTEMPTS
    )
    return "synthesize" if needs_retry else "render_report"


def build_graph(deps: AgentDeps) -> Any:
    """Compile the report graph bound to ``deps``."""
    nodes = build_nodes(deps)
    graph = StateGraph(ReportState)
    for name, node in nodes.items():
        graph.add_node(name, node)  # type: ignore[call-overload]  # langgraph overloads
    graph.add_edge(START, "validate_request")
    graph.add_conditional_edges("validate_request", _after_validate)
    graph.add_edge("fetch_metrics", "plan_news")
    graph.add_edge("plan_news", "collect_news")
    graph.add_edge("collect_news", "synthesize")
    graph.add_edge("synthesize", "verify_narrative")
    graph.add_conditional_edges("verify_narrative", _after_verify)
    graph.add_edge("render_report", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_report(
    deps: AgentDeps, raw_request: dict[str, Any], *, run_id: str | None = None
) -> ReportState:
    """Run one report. The audit trail is flushed by the nodes; a write failure aborts the run."""
    run_id = run_id or str(uuid4())
    deps.recorder.record(
        actor="system",
        node="run",
        event="run_start",
        inputs=raw_request,
        details={"models": ",".join(f"{k}={v}" for k, v in sorted(deps.models.items()))},
    )
    await deps.recorder.flush()
    app = build_graph(deps)
    result = await app.ainvoke(
        ReportState(run_id=run_id, raw_request=raw_request),
        config={"recursion_limit": RECURSION_LIMIT},
    )
    return ReportState.model_validate(result)
