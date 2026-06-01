"""
Optional LangGraph orchestration layer for the AI Workflow DSL Compiler.

The compiler remains deterministic. LangGraph is used only as an agent
orchestration shell around existing compiler artifacts:
  observe -> deterministic_diagnose -> optional_llm_review -> synthesize

If langgraph is not installed, this module returns a clear fallback report and
uses the deterministic CompilerAgent directly.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TypedDict

from agentic_debugger import CompilerAgent
from llm_layer import OptionalLLMReviewer


class CompilerAgentState(TypedDict, total=False):
    source: str
    compile_results: Dict[str, Any]
    runtime_result: Optional[Dict[str, Any]]
    runtime_error: Optional[Dict[str, Any]]
    deterministic_report: Dict[str, Any]
    llm_review: Dict[str, Any]
    final_report: Dict[str, Any]
    execution_mode: str


class LangGraphCompilerAgent:
    def __init__(self, llm_provider: Optional[str] = None, llm_model: Optional[str] = None, enable_llm: bool = False):
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.enable_llm = enable_llm

    def run(
        self,
        source: str,
        compile_results: Dict[str, Any],
        runtime_result: Optional[Dict[str, Any]] = None,
        runtime_error: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return self._fallback(source, compile_results, runtime_result, runtime_error, "langgraph_not_installed")

        workflow = StateGraph(CompilerAgentState)
        workflow.add_node("observe", self._observe)
        workflow.add_node("deterministic_diagnose", self._deterministic_diagnose)
        workflow.add_node("optional_llm_review", self._optional_llm_review)
        workflow.add_node("synthesize", self._synthesize)
        workflow.set_entry_point("observe")
        workflow.add_edge("observe", "deterministic_diagnose")
        workflow.add_edge("deterministic_diagnose", "optional_llm_review")
        workflow.add_edge("optional_llm_review", "synthesize")
        workflow.add_edge("synthesize", END)

        app = workflow.compile()
        initial: CompilerAgentState = {
            "source": source,
            "compile_results": compile_results,
            "runtime_result": runtime_result,
            "runtime_error": runtime_error,
            "execution_mode": "langgraph",
        }
        return dict(app.invoke(initial)).get("final_report", {})

    def _observe(self, state: CompilerAgentState) -> CompilerAgentState:
        results = state.get("compile_results", {})
        state["observation"] = {
            "source_language": results.get("source_language"),
            "success": results.get("success"),
            "token_count": len(results.get("tokens", []) or []),
            "tac_count": len(results.get("tac", []) or []),
            "asm_count": len(results.get("asm", []) or []),
        }
        return state

    def _deterministic_diagnose(self, state: CompilerAgentState) -> CompilerAgentState:
        report = CompilerAgent().analyze(
            state.get("source", ""),
            state.get("compile_results", {}),
            runtime_result=state.get("runtime_result"),
            runtime_error=state.get("runtime_error"),
        )
        state["deterministic_report"] = report.to_dict()
        return state

    def _optional_llm_review(self, state: CompilerAgentState) -> CompilerAgentState:
        if not self.enable_llm:
            reviewer = OptionalLLMReviewer(provider="none")
        else:
            reviewer = OptionalLLMReviewer(provider=self.llm_provider, model=self.llm_model)
        review = reviewer.review(
            state.get("source", ""),
            state.get("compile_results", {}),
            state.get("deterministic_report", {}),
        )
        state["llm_review"] = review.to_dict()
        return state

    def _synthesize(self, state: CompilerAgentState) -> CompilerAgentState:
        final_report = dict(state.get("deterministic_report", {}))
        final_report["execution_mode"] = state.get("execution_mode", "langgraph")
        final_report["langgraph_trace"] = [
            "observe",
            "deterministic_diagnose",
            "optional_llm_review",
            "synthesize",
        ]
        final_report["llm_review"] = state.get("llm_review", {})
        state["final_report"] = final_report
        return state

    def _fallback(
        self,
        source: str,
        compile_results: Dict[str, Any],
        runtime_result: Optional[Dict[str, Any]],
        runtime_error: Optional[Dict[str, Any]],
        reason: str,
    ) -> Dict[str, Any]:
        report = CompilerAgent().analyze(source, compile_results, runtime_result=runtime_result, runtime_error=runtime_error).to_dict()
        report["execution_mode"] = f"deterministic_fallback:{reason}"
        report["langgraph_trace"] = ["fallback_to_compiler_agent"]
        if self.enable_llm:
            llm_review = OptionalLLMReviewer(provider=self.llm_provider, model=self.llm_model).review(source, compile_results, report)
        else:
            llm_review = OptionalLLMReviewer(provider="none").review(source, compile_results, report)
        report["llm_review"] = llm_review.to_dict()
        return report
