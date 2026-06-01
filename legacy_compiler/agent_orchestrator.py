"""Unified agent entrypoint for deterministic, LLM, and LangGraph modes."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agentic_debugger import AgentReport, CompilerAgent
from langgraph_layer import LangGraphCompilerAgent
from llm_layer import OptionalLLMReviewer


class AgentReportAdapter:
    """Small adapter so existing CLI/Web code can call to_dict()/to_text()."""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return self.payload

    def to_text(self) -> str:
        lines = [
            f"Agent Role: {self.payload.get('role', 'Compiler Agent')}",
            f"Execution Mode: {self.payload.get('execution_mode', 'deterministic')}",
            f"Status: {self.payload.get('status', 'unknown')}",
            f"Validation Score: {self.payload.get('validation_score', '?')}/100",
            "",
            "Summary:",
            f"  {self.payload.get('summary', '')}",
            "",
            "Architecture Trace:",
        ]
        for item in self.payload.get("architecture_trace", []) or []:
            lines.append(f"  - {item}")
        lines.append("")
        lines.append("LangGraph Trace:")
        for item in self.payload.get("langgraph_trace", []) or ["not enabled"]:
            lines.append(f"  - {item}")
        lines.append("")
        lines.append("Workflow Graph:")
        graph = self.payload.get("workflow_graph", []) or []
        lines.extend(f"  - {edge}" for edge in graph) if graph else lines.append("  - No AI workflow graph detected.")
        lines.append("")
        lines.append("Findings:")
        findings = self.payload.get("findings", []) or []
        if findings:
            for f in findings:
                loc = f"Line {f.get('line')}: " if f.get("line") else ""
                lines.append(f"  [{str(f.get('severity', 'info')).upper()}] {f.get('category', 'General')}: {loc}{f.get('message', '')}")
                if f.get("suggestion"):
                    lines.append(f"      Fix: {f.get('suggestion')}")
        else:
            lines.append("  - No issues found by the agent.")
        lines.append("")
        lines.append("Suggested Fixes:")
        fixes = self.payload.get("suggested_fixes", []) or []
        lines.extend(f"  - {fix}" for fix in fixes) if fixes else lines.append("  - No fixes required.")

        llm = self.payload.get("llm_review") or {}
        lines.append("")
        lines.append("Optional LLM Review:")
        lines.append(f"  Enabled: {llm.get('enabled', False)}")
        lines.append(f"  Provider: {llm.get('provider', 'none')}")
        lines.append(f"  Model: {llm.get('model', 'none')}")
        lines.append(f"  Status: {llm.get('status', 'disabled')}")
        if llm.get("summary"):
            lines.append(f"  Summary: {llm.get('summary')}")
        recs = llm.get("recommendations", []) or []
        if recs:
            lines.append("  Recommendations:")
            lines.extend(f"    - {item}" for item in recs)

        lines.append("")
        lines.append("CV Evidence:")
        for item in self.payload.get("cv_evidence", []) or []:
            lines.append(f"  - {item}")
        return "\n".join(lines)


def build_agent_report(
    source: str,
    compile_results: Dict[str, Any],
    runtime_result: Optional[Dict[str, Any]] = None,
    runtime_error: Optional[Dict[str, Any]] = None,
    backend: str = "deterministic",
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> AgentReportAdapter:
    backend = (backend or "deterministic").lower()

    if backend == "deterministic":
        report: AgentReport = CompilerAgent().analyze(source, compile_results, runtime_result=runtime_result, runtime_error=runtime_error)
        payload = report.to_dict()
        payload["execution_mode"] = "deterministic"
        payload["langgraph_trace"] = ["not enabled"]
        payload["llm_review"] = OptionalLLMReviewer(provider="none").review(source, compile_results, payload).to_dict()
        return AgentReportAdapter(payload)

    if backend == "llm":
        report = CompilerAgent().analyze(source, compile_results, runtime_result=runtime_result, runtime_error=runtime_error)
        payload = report.to_dict()
        payload["execution_mode"] = "deterministic_plus_optional_llm"
        payload["langgraph_trace"] = ["not enabled"]
        payload["llm_review"] = OptionalLLMReviewer(provider=llm_provider, model=llm_model).review(source, compile_results, payload).to_dict()
        return AgentReportAdapter(payload)

    if backend == "langgraph":
        payload = LangGraphCompilerAgent(enable_llm=False).run(source, compile_results, runtime_result, runtime_error)
        return AgentReportAdapter(payload)

    if backend == "langgraph-llm":
        payload = LangGraphCompilerAgent(llm_provider=llm_provider, llm_model=llm_model, enable_llm=True).run(
            source, compile_results, runtime_result, runtime_error
        )
        return AgentReportAdapter(payload)

    # Auto gives the strongest requested path while preserving graceful fallback.
    if backend == "auto":
        payload = LangGraphCompilerAgent(llm_provider=llm_provider, llm_model=llm_model, enable_llm=True).run(
            source, compile_results, runtime_result, runtime_error
        )
        return AgentReportAdapter(payload)

    raise ValueError("Unknown agent backend. Use deterministic, llm, langgraph, langgraph-llm, or auto.")
